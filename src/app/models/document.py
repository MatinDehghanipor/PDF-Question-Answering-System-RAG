"""Document model.

Implements part of the "Document and Page Registry" component (SDD §4):
tracks per-user document metadata and status through the full upload →
processing → review → ready/discarded/failed lifecycle.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import DocumentStatus


class Document(Base):
    """A single uploaded PDF file owned by a user.

    Attributes:
        id: Surrogate primary key.
        user_id: Foreign key to the owning user (per-user isolation, NFR-21).
        filename: Original upload filename.
        upload_date: When the file was uploaded.
        status: Lifecycle status (uploaded/processing/awaiting_feedback/ready/
            discarded/failed).
        page_count: Number of pages detected in the PDF.
        owner: The :class:`User` who owns this document.
        pages: Pages of this document (one-to-many).
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    upload_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, values_callable=lambda e: [m.value for m in e]),
        default=DocumentStatus.UPLOADED,
        nullable=False,
        index=True,
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships (string references avoid circular imports)
    owner: Mapped["User"] = relationship(back_populates="documents")  # noqa: F821
    pages: Mapped[list["Page"]] = relationship(  # noqa: F821
        back_populates="document", cascade="all, delete-orphan"
    )