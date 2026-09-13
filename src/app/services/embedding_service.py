"""Embedding Service + Vector Index placeholder.

Implements the "Embedding Service" and "Vector Index / Store" components
(SDD §4): converts approved chunks and queries into vectors, persists them in
a per-user-partitioned vector store, and serves top-k similarity search.
Model name is configurable via ``settings.EMBEDDING_MODEL_NAME`` and store
path via ``settings.VECTOR_STORE_PATH`` (NFR-25).  Real implementation is
added in Phase 6 — no business logic yet.
"""

# TODO(Phase 6): implement embed_texts(), index_chunk(), search_top_k()
# using sentence-transformers + ChromaDB.