"""Chunker placeholder.

Implements the "Chunker" component (SDD §4): splits an approved page's
content into indexable, type- and order-traceable chunks.  Chunk size and
overlap are configurable via ``settings.CHUNK_SIZE_TOKENS`` and
``settings.CHUNK_OVERLAP_TOKENS`` (NFR-25, OD-1).  Real implementation is
added in Phase 6 — no business logic yet.
"""

# TODO(Phase 6): implement chunk_page(page_content, chunk_size, overlap) -> list[Chunk]