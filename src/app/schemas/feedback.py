"""Pydantic schemas for answer feedback.

Mirrors :mod:`app.models.feedback`.  Shapes for POST /feedback (FR-31, FR-32)
and the feedback listing endpoint.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FeedbackRating


class FeedbackRequest(BaseModel):
    """Request body for POST /feedback.

    Attributes:
        answer_id: The answer being rated.  The originating query is derived
            from this answer server-side, so clients do not (and cannot)
            supply a mismatched ``query_id`` — the SDD §6.2 diagram shows
            ``query_id`` on the wire, but the answer already determines it
            uniquely (``Answer.query_id`` is one-to-one and NOT NULL).
        rating: ``positive``/``negative``, or omitted.
        comment: Optional free-text comment (nullable).

    Both signals are individually optional (FR-31: "positive/negative rating,
    optional free-text comment"; UC9: "rates the answer ... and/or adds a
    comment"), but at least one must be present.  That cross-field rule is
    enforced by :func:`app.services.feedback_service.submit_feedback` rather
    than here, so it yields the 400 the phase spec calls for instead of
    Pydantic's 422 — an empty submission is a well-formed request that asks
    for nothing, not a malformed one.
    """

    answer_id: int
    rating: FeedbackRating | None = None
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    """Public representation of a feedback record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    query_id: int
    answer_id: int
    rating: FeedbackRating | None = None
    comment: str | None = None
    timestamp: datetime
