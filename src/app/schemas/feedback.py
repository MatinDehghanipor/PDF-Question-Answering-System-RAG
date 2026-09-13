"""Pydantic schemas for answer feedback.

Mirrors :mod:`app.models.feedback`.  Shapes for POST /feedback (FR-28, FR-29)
and the feedback listing endpoint.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FeedbackRating


class FeedbackCreate(BaseModel):
    """Request body for POST /feedback.

    Attributes:
        query_id: The query whose answer is being rated.
        answer_id: The answer being rated.
        rating: positive or negative.
        comment: Optional free-text comment (nullable).
    """

    query_id: int
    answer_id: int
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    """Public representation of a feedback record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    query_id: int
    answer_id: int
    rating: FeedbackRating
    comment: str | None = None
    timestamp: datetime