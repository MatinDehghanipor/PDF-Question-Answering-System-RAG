"""Feedback model.

Implements the "Answer Feedback Store" component (SDD §4): persists user
ratings/comments on answers, linked back to the query, answer, and mode used.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import FeedbackRating


class Feedback(Base):
    """A single rating/comment left by a user on an answer.

    Attributes:
        id: Surrogate primary key.
        query_id: Foreign key to the query that produced the answer.
        answer_id: Foreign key to the answer being rated.
        rating: ``positive``, ``negative``, or NULL when the user supplied
            only a comment.  FR-31 lists the rating and the comment as two
            independently optional signals (UC9 says "rates the answer ... and/
            or adds a comment"), so requiring a rating here would make the
            comment-only path impossible.
        comment: Optional free-text comment (nullable).
        timestamp: When the feedback was submitted.
        query: The :class:`Query` this feedback refers to.

    Note:
        The ``mode`` and ``chunks used`` linkage required by FR-32 is *not*
        duplicated onto this table.  It is reachable by joining
        ``Feedback -> Answer -> Query``: ``Query.mode`` holds the mode
        (rag/raw) and ``Answer.source_chunk_ids`` holds the chunks actually
        used (NULL in Raw Mode).  Storing either here would be a second copy
        of the same fact that could drift out of sync with the answer.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query_id: Mapped[int] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rating: Mapped[FeedbackRating | None] = mapped_column(
        Enum(FeedbackRating, values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship (string reference avoids circular imports)
    query: Mapped["Query"] = relationship(back_populates="feedback")  # noqa: F821