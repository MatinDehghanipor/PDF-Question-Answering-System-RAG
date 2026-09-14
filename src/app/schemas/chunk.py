"""Pydantic schemas for chunk data.

Mirrors :mod:`app.models.chunk`.  Chunk records are nested inside page review
responses and answers' source chunk metadata.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ChunkReviewStatus, ChunkType


class ChunkOut(BaseModel):
    """Public representation of a chunk."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    page_id: int
    chunk_type: ChunkType
    text: str | None = None
    table_markdown: str | None = None
    image_caption: str | None = None
    image_path: str | None = None
    reading_order: int
    excluded: bool = False
    review_status: ChunkReviewStatus
    reviewed_at: datetime | None = None