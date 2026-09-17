"""Chunker — real implementation (Phase 6).

Implements the "Chunker" component (SDD §4): when a page is approved,
``split_and_index_page()`` reads its approved/edited chunks, splits long
text chunks (OD-1), batch-embeds everything, and upserts into the user's
Chroma collection with full metadata traceability (FR-20, FR-21).

Also provides ``remove_embeddings_for_document()`` for discard/delete flows.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.embedding import Embedding
from app.models.enums import ChunkReviewStatus
from app.models.page import Page
from app.services.embedding_service import embed_texts, should_split_chunk, split_text_chunk
from app.services.vector_store import delete_chunks_for_document, upsert_chunks

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# FR-37 reprocessing guard
# ──────────────────────────────────────────────────────────────────────


def _check_reindex_guard(page: Page, db: Session) -> None:
    """Warn if *page* already has Embedding rows (FR-37 defense-in-depth).

    The primary gatekeeper is the page status machine (only approved pages
    are indexed), but this in-DB check catches any code path that calls
    ``split_and_index_page`` twice for the same page — for example during
    testing or after an improper status transition.
    """
    existing = db.query(Embedding).filter(
        Embedding.chunk_id.in_(
            db.query(Chunk.id).filter(Chunk.page_id == page.id),
        ),
    ).first()
    if existing is not None:
        logger.warning(
            "FR-37 guard: page %d already has Embedding rows — re-indexing "
            "may duplicate vectors.  page.status=%s.",
            page.id, page.status.value if page.status else "None",
        )


def split_and_index_page(db: Session, page: Page, user_id: int) -> None:
    """Index a page's approved chunks into Chroma (FR-20, FR-21).

    Called from ``approve_page()`` in the review service whenever a page
    is approved (both Round 1 and Round 2 funnel through the same path).

    1. Collect all chunks with ``review_status IN (approved, edited)``.
    2. For each ``text`` chunk exceeding ``CHUNK_SIZE_TOKENS``, split it
       into sub-chunks (OD-1).  ``table`` / ``image`` chunks are never split.
    3. Batch-embed all resulting texts in ONE call.
    4. Upsert into the user's Chroma collection with metadata.
    5. Write one ``Embedding`` bookkeeping row per stored vector.

    Args:
        db: SQLAlchemy session.
        page: The approved Page.
        user_id: The document owner's id.
    """
    _check_reindex_guard(page, db)
    doc = page.document

    # 1. Approved/edited chunks only (never rejected/pending).
    chunks = (
        db.query(Chunk)
        .filter(
            Chunk.page_id == page.id,
            Chunk.review_status.in_([ChunkReviewStatus.APPROVED, ChunkReviewStatus.EDITED]),
        )
        .order_by(Chunk.reading_order, Chunk.sub_index)
        .all()
    )

    if not chunks:
        logger.info("Page %d has no indexable chunks (all rejected?).", page.id)
        return

    # 2. Build list of (embed_text, metadata_dict, chunk_ref)
    embed_inputs: list[str] = []
    metadata_list: list[dict] = []
    chunk_records: list[tuple] = []  # (embed_text, metadata, chunk, sub_index)

    for c in chunks:
        # Determine text to embed per chunk type
        if c.chunk_type.value == "text":
            text = c.text or ""
            if should_split_chunk(text):
                sub_chunks = split_text_chunk(text, c.id, c.reading_order)
                for sc in sub_chunks:
                    embed_inputs.append(sc["text"])
                    metadata_list.append({
                        "document_id": doc.id,
                        "document_filename": doc.filename,
                        "page_id": page.id,
                        "chunk_type": "text",
                        "reading_order": sc["reading_order"],
                        "sub_index": sc["sub_index"],
                        "page_number": page.page_number,
                    })
                    chunk_records.append((sc["text"], sc, c, sc["sub_index"]))
                continue
        elif c.chunk_type.value == "table":
            text = c.table_markdown or ""
        elif c.chunk_type.value == "image":
            text = c.image_caption or ""
        else:
            text = ""

        if not text.strip():
            continue

        embed_inputs.append(text)
        metadata_list.append({
            "document_id": doc.id,
            "document_filename": doc.filename,
            "page_id": page.id,
            "chunk_type": c.chunk_type.value,
            "reading_order": c.reading_order,
            "sub_index": c.sub_index,
            "page_number": page.page_number,
        })
        chunk_records.append((text, None, c, 0))

    if not embed_inputs:
        logger.info("Page %d has no non-empty chunks to embed.", page.id)
        return

    # 3. Batch-embed all texts
    vectors = embed_texts(embed_inputs)
    if len(vectors) != len(embed_inputs):
        logger.error("Embedding count mismatch: %d texts vs %d vectors.", len(embed_inputs), len(vectors))
        return

    # 4. Upsert into Chroma
    chunk_ids = []
    documents = []
    metadatas = []
    idx = 0
    for text, sc, chunk, _ in chunk_records:
        vid = f"chunk_{chunk.id}" if sc is None else f"chunk_{chunk.id}_sub{sc['sub_index']}"
        chunk_ids.append(vid)
        documents.append(text)
        metadatas.append(metadata_list[idx])
        idx += 1

    upsert_chunks(user_id, chunk_ids, vectors, documents, metadatas)

    # 5. Write Embedding bookkeeping rows
    now = datetime.utcnow()
    for chunk in chunks:
        existing = db.query(Embedding).filter(Embedding.chunk_id == chunk.id).first()
        if existing:
            existing.embedding_model_version = settings.EMBEDDING_MODEL_NAME
        else:
            db.add(Embedding(chunk_id=chunk.id, embedding_model_version=settings.EMBEDDING_MODEL_NAME))
    db.flush()

    logger.info(
        "Indexed page %d: %d vectors upserted for user %d.",
        page.id, len(embed_inputs), user_id,
    )


def remove_embeddings_for_document(user_id: int, document_id: int) -> None:
    """Remove all chunk embeddings for a document from the user's vector store.

    Phase 6 real implementation: delegates to ``vector_store.delete_chunks_for_document``.
    The caller must ensure *user_id* matches the document's owner.

    Args:
        user_id: Owner of the document whose vectors should be removed.
        document_id: The document id to remove from the vector index.
    """
    delete_chunks_for_document(user_id, document_id)
    logger.info("Removed embeddings for document %d (user %d).", document_id, user_id)