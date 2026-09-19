"""Review service — page approval, unsatisfied, document discard (Phase 5).

Implements the human-review decision logic for the "Document and Page Registry"
component (SDD §4): ``approve_page``, ``mark_unsatisfied``, ``discard_document``,
and ``approve_all_pending`` drive the page/document status machine.

Round-2 rejection now calls the real ``discard_document()`` which performs
full cleanup (files, pages, chunks, embeddings stub).
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.enums import (
    ChunkReviewStatus,
    DocumentStatus,
    PageStatus,
)
from app.models.page import Page
from app.services.chunker import split_and_index_page
from app.services.llm_service import trigger_llm_review
from app.utils.pdf_utils import safe_unlink
from app.services.vector_store import delete_chunks_for_document

logger = logging.getLogger(__name__)


def approve_page(page: Page, db: Session) -> None:
    """Approve a single page's content (see Phase 4 docstring)."""
    if page.status != PageStatus.AWAITING_FEEDBACK:
        raise ValueError(
            f"Cannot approve page {page.id}: status is '{page.status.value}', "
            f"expected 'awaiting_feedback'."
        )
    now = datetime.utcnow()
    for chunk in page.chunks:
        if chunk.review_status == ChunkReviewStatus.REJECTED:
            continue
        if chunk.review_status == ChunkReviewStatus.EDITED:
            pass
        else:
            chunk.review_status = ChunkReviewStatus.APPROVED
        chunk.reviewed_at = now
    page.status = PageStatus.APPROVED
    page.updated_at = now
    db.flush()
    _index_page_and_update_status(page, db)
def mark_unsatisfied(page: Page, db: Session, note: str | None = None) -> None:
    """Mark a page unsatisfactory — Round 1 escalates, Round 2 discards document."""
    if page.status != PageStatus.AWAITING_FEEDBACK:
        raise ValueError(f"Cannot mark page {page.id} unsatisfied: status is '{page.status.value}'.")
    page.review_note = note
    if page.review_round == 2:
        logger.warning("Page %d rejected Round 2 — discarding document %d.", page.id, page.document_id)
        discard_document(db, page.document_id)
    else:
        page.status = PageStatus.LLM_REVIEW
        page.updated_at = datetime.utcnow()
        db.flush()
        try:
            trigger_llm_review(db, page.id, note=note)
        except Exception as exc:
            logger.error("LLM Review failed for page %d: %s", page.id, exc)


def discard_document(db: Session, document_id: int) -> None:
    """Discard entire document — cascade cleanup (FR-16).

    Keeps Document row with status=discarded (visible record, unlike FR-23 hard delete).
    """
    doc = db.get(Document, document_id)
    if doc is None:
        raise ValueError(f"Document {document_id} not found.")
    if doc.status == DocumentStatus.DISCARDED:
        raise ValueError(f"Document {document_id} is already discarded.")

    logger.info("Discarding document %d (user=%d).", doc.id, doc.user_id)
    # Phase 6: Remove vectors from Chroma BEFORE deleting SQL rows so that a
    # failure in vector deletion can be safely retried without orphaning either
    # side — the SQL rows still exist, so we know what to clean up next time.
    delete_chunks_for_document(doc.user_id, doc.id)

    for p in list(doc.pages or []):
        db.query(Chunk).filter(Chunk.page_id == p.id).delete()
        db.delete(p)
    db.flush()

    storage_dir = Path(settings.FILE_STORAGE_PATH) / str(doc.user_id)
    pdf_path = storage_dir / f"{doc.id}.pdf"
    safe_unlink(pdf_path)
    images_dir = storage_dir / "_images"
    if images_dir.exists():
        shutil.rmtree(images_dir, ignore_errors=True)

    doc.status = DocumentStatus.DISCARDED
    db.flush()
    logger.info("Document %d discarded.", doc.id)


def approve_all_pending(document: Document, db: Session) -> int:
    """Approve every awaiting-feedback page of *document*."""
    pending = [p for p in document.pages if p.status == PageStatus.AWAITING_FEEDBACK]
    for p in pending:
        approve_page(p, db)
    return len(pending)


def _index_page_and_update_status(page: Page, db: Session) -> None:
    """Index the approved page's chunks into Chroma, then update document status.

    Phase 6 real implementation: delegates to ``split_and_index_page()`` from
    the chunker service.  If indexing fails (embedding error, Chroma write
    failure), the exception propagates up through ``approve_page()`` so the
    caller's ``db.commit()`` is never reached — the transaction rolls back,
    leaving the page's chunks in their pre-approval state.  This satisfies the
    Phase 6 requirement that indexing succeeding is a precondition for the
    final "Approved" status being persisted.

    NFR-12 atomicity: if the Chroma upsert succeeds but the subsequent DB
    status update fails, the Chroma vectors are removed so no orphaned
    embeddings remain in the vector store.
    """
    doc = page.document
    user_id = doc.user_id
    try:
        split_and_index_page(db, page, user_id)
    except Exception:
        logger.error("Indexing failed for page %d — transaction will roll back.", page.id)
        raise
    try:
        _update_document_status_if_ready(doc, db)
    except Exception:
        # Chroma vectors were written but DB update failed — roll back the
        # vectors so we are not left with orphaned embeddings.
        logger.error(
            "DB status update failed for page %d (document %d) after indexing — "
            "removing Chroma vectors to maintain atomicity.",
            page.id, doc.id,
        )
        try:
            delete_chunks_for_document(user_id, doc.id)
        except Exception as cleanup_exc:
            logger.error(
                "Failed to clean up Chroma vectors after DB failure for page %d: %s",
                page.id, cleanup_exc,
            )
        raise


def _update_document_status_if_ready(document: Document, db: Session) -> None:
    """Mark document ready if every active page is approved."""
    active = [p for p in (document.pages or []) if p.status != PageStatus.DISCARDED]
    if active and all(p.status == PageStatus.APPROVED for p in active):
        document.status = DocumentStatus.READY
        logger.info("Document %d is now READY.", document.id)