"""Chunker placeholder (Phase 5 stub).

Implements the "Chunker" component (SDD §4): splits an approved page's
content into indexable chunks, and provides a hook for removing document
embeddings during discard operations.

Phase 5 adds the stub ``remove_embeddings_for_document(document_id)`` called
by ``discard_document`` in the review service.  Real implementation is Phase 6.
"""

import logging

logger = logging.getLogger(__name__)


def enqueue_for_indexing(page_id: int) -> None:
    """Enqueue an approved page for chunking, embedding, and indexing (Phase 6)."""
    pass


def remove_embeddings_for_document(document_id: int) -> None:
    """Remove all stored embeddings for a discarded document.

    Called by :func:`app.services.review_service.discard_document` during
    document discard (FR-16).  Real implementation is in Phase 6 when the
    vector store exists.

    Args:
        document_id: The id of the document whose embeddings should be removed.
    """
    # TODO(Phase 6): query vector store for all embeddings linked to chunks
    # belonging to this document's pages and delete them.
    logger.info(
        "# TODO(Phase 6): remove embeddings for document %d from vector store.",
        document_id,
    )