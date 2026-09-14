"""Chunker placeholder (Phase 4 stub).

Implements the "Chunker" component (SDD §4): splits an approved page's
content into indexable, type- and order-traceable chunks.  Chunk size and
overlap are configurable via ``settings.CHUNK_SIZE_TOKENS`` and
``settings.CHUNK_OVERLAP_TOKENS`` (NFR-25, OD-1).

Phase 4 adds the stub entry point ``enqueue_for_indexing(page_id)`` that the
review service calls when a page is approved.  Real implementation is Phase 6.
"""

import logging

logger = logging.getLogger(__name__)


def enqueue_for_indexing(page_id: int) -> None:
    """Enqueue an approved page for chunking, embedding, and indexing.

    Called by :func:`app.services.review_service.approve_page` after a page
    is approved.  Phase 6 replaces the body with real logic.

    Args:
        page_id: The id of the approved Page whose chunks should be indexed.
    """
    # TODO(Phase 6): implement chunk_page() and invoke embedding service.
    logger.info(
        "# TODO(Phase 6): chunk, embed, and index approved chunks for page %d.",
        page_id,
    )