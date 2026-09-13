"""Pydantic schemas for embedding audit records.

Mirrors :mod:`app.models.embedding`.  The Embedding record is a bookkeeping
row only — the actual vector lives in the Chroma vector store (Phase 6).
"""

from pydantic import BaseModel, ConfigDict


class EmbeddingOut(BaseModel):
    """Public representation of an embedding audit record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_id: int
    embedding_model_version: str