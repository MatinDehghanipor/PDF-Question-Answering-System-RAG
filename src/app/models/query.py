"""Query model.

Records every natural-language question a user asks (SDD §7), including the
retrieval k-value and the mode (RAG vs Raw), so answers and feedback can be
linked back to the exact query and per-user isolation (NFR-21) applies.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import QueryMode


class Query(Base):
    """A single user question.

    Attributes:
        id: Surrogate primary key.
        user_id: Foreign key to the user who asked (per-user isolation, NFR-21).
        text: The question text.
        timestamp: When the question was asked.
        k_value: Top-k used for RAG retrieval (None for Raw Mode).
        mode: rag or raw.
        user: The :class:`User` who asked.
        answer: The answer produced for this query (one-to-one).
        feedback: Feedback left on answers to this query (one-to-many).
    """

    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    k_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[QueryMode] = mapped_column(
        Enum(QueryMode, values_callable=lambda e: [m.value for m in e]),
        default=QueryMode.RAG,
        nullable=False,
        index=True,
    )

    # Relationships (string references avoid circular imports)
    user: Mapped["User"] = relationship(back_populates="queries")  # noqa: F821
    answer: Mapped["Answer | None"] = relationship(  # noqa: F821
        back_populates="query", uselist=False, cascade="all, delete-orphan"
    )
    feedback: Mapped[list["Feedback"]] = relationship(  # noqa: F821
        back_populates="query", cascade="all, delete-orphan"
    )