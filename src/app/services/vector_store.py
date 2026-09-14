"""Vector Store — ChromaDB wrapper (Phase 6).

Implements the "Vector Index / Store" component (SDD §4): persists chunk
embeddings in a per-user-partitioned ChromaDB collection and provides
CRUD operations for indexing and deletion.

[WORKING DEFAULT — OD-5]: One ChromaDB collection per user
(``user_{user_id}_chunks``), owned and managed separately.  This makes
NFR-10's "own index partition" literally true and keeps each collection
small at the ~100-document/user scale.

ChromaDB's default HNSW index satisfies NFR-9 (sub-linear approximate
nearest neighbor search) out of the box.
"""

import logging
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level Chroma client (persistent, created once).
_client: chromadb.PersistentClient | None = None


def _get_client() -> chromadb.PersistentClient:
    """Return the shared Chroma PersistentClient (disk-persisted per NFR-7)."""
    global _client
    if _client is None:
        store_path = Path(settings.VECTOR_STORE_PATH)
        store_path.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(store_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info("Chroma persistent client at '%s'.", store_path)
    return _client


def _collection_name(user_id: int) -> str:
    """Deterministic collection name per user (OD-5 default)."""
    return f"user_{user_id}_chunks"


def get_user_collection(user_id: int):
    """Get or create the Chroma collection for *user_id*."""
    client = _get_client()
    return client.get_or_create_collection(
        name=_collection_name(user_id),
        # Note: We pass precomputed embeddings explicitly, so no
        # default embedding function should be used.
        metadata={"hnsw:space": "cosine"},
    )


def upsert_chunks(
    user_id: int,
    chunk_ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict],
) -> None:
    """Add or update chunk embeddings in the user's collection."""
    if not chunk_ids:
        return
    coll = get_user_collection(user_id)
    coll.add(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )
    logger.debug("Upserted %d chunks for user %d.", len(chunk_ids), user_id)


def delete_chunks_for_document(user_id: int, document_id: int) -> None:
    """Remove all chunk embeddings for a given document from the user's collection.

    Uses Chroma's metadata filtering: ``{"document_id": document_id}``.
    Does NOT raise if no matching entries exist.
    """
    try:
        coll = get_user_collection(user_id)
        coll.delete(where={"document_id": document_id})
        logger.info("Deleted vectors for document %d (user %d).", document_id, user_id)
    except Exception as exc:
        logger.warning("Error deleting vectors for doc %d (user %d): %s", document_id, user_id, exc)


def delete_chunks_by_ids(user_id: int, chunk_ids: list[str]) -> None:
    """Remove specific chunks by their string IDs."""
    if not chunk_ids:
        return
    try:
        coll = get_user_collection(user_id)
        coll.delete(ids=chunk_ids)
        logger.debug("Deleted %d chunk vectors for user %d.", len(chunk_ids), user_id)
    except Exception as exc:
        logger.warning("Error deleting chunk vectors: %s", exc)