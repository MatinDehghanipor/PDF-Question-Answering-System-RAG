"""Chunk model.

Implements the chunk-level records of the "Document and Page Registry"
component (SDD §4): each chunk is a type- and order-traceable piece of an
approved page's content, plus its review state.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ChunkReviewStatus, ChunkType


class Chunk(Base):
    """A single indexable piece of content extracted from an approved page.

    Attributes:
        id: Surrogate primary key.
        page_id: Foreign key to the page this chunk came from.
        chunk_type: text / table / image.
        text: Chunk text content for text-type chunks.
        table_markdown: Markdown serialization of a table-type chunk (nullable).
        image_caption: Caption for an image-type chunk (nullable).
        image_path: Filesystem path to an extracted image (nullable).
        reading_order: Order of this chunk within its page (for reconstruction).
        excluded: Flag set by the reviewer to exclude this chunk from indexing
            (Phase 4).  Once ``true``, the chunk gets ``review_status = rejected``
            upon the next page approval.
        review_status: pending / approved / edited / rejected.
        reviewed_at: When a human/LLM reviewer last touched this chunk (nullable).
        page: The :class:`Page` this chunk belongs to.
    """

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_type: Mapped[ChunkType] = mapped_column(
        Enum(ChunkType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    review_status: Mapped[ChunkReviewStatus] = mapped_column(
        Enum(ChunkReviewStatus, values_callable=lambda e: [m.value for m in e]),
        default=ChunkReviewStatus.PENDING,
        nullable=False,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships (string references avoid circular imports)
    page: Mapped["Page"] = relationship(back_populates="chunks")  # noqa: F821