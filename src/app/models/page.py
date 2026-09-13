"""Page model.

Implements part of the "Document and Page Registry" component (SDD §4):
tracks per-page status/review state through the full lifecycle, including
the extraction method used and the quality score that gates OCR fallback.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ExtractionMethod, PageStatus


class Page(Base):
    """A single page within a document, tracked through the ingestion pipeline.

    Attributes:
        id: Surrogate primary key.
        document_id: Foreign key to the owning document.
        page_number: 1-based page index within the document.
        status: initial_processing / awaiting_feedback / llm_review / approved.
        extraction_method: native / ocr / llm_vision (nullable until first pass).
        quality_score: 0..1 quality score from the Quality Scorer (nullable).
        review_round: 1 or 2 — how many human-review rounds have been attempted.
        updated_at: Last time this page's state changed.
        document: The :class:`Document` this page belongs to.
        chunks: Chunks produced from this page (one-to-many).
    """

    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PageStatus] = mapped_column(
        Enum(PageStatus, values_callable=lambda e: [m.value for m in e]),
        default=PageStatus.INITIAL_PROCESSING,
        nullable=False,
        index=True,
    )
    extraction_method: Mapped[ExtractionMethod | None] = mapped_column(
        Enum(ExtractionMethod, values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_round: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships (string references avoid circular imports)
    document: Mapped["Document"] = relationship(back_populates="pages")  # noqa: F821
    chunks: Mapped[list["Chunk"]] = relationship(  # noqa: F821
        back_populates="page", cascade="all, delete-orphan"
    )