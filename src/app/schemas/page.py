"""Pydantic schemas for the page review endpoints.

Mirrors :mod:`app.models.page`.  Shapes for GET/DELETE /pages/{id}/review —
the backend sends extracted page content for human review, and the client
returns an approve/edit/reject decision (FR-6..FR-12, Phase 4).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ExtractionMethod, PageStatus


class PageOut(BaseModel):
    """Public representation of a page and its current ingestion state."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    page_number: int
    status: PageStatus
    extraction_method: ExtractionMethod | None = None
    quality_score: float | None = None
    review_round: int
    updated_at: datetime


class PageReviewRequest(BaseModel):
    """Human review decision body for POST /pages/{id}/review.

    Attributes:
        decision: approve | edit | reject.
        edited_content: Required when decision == "edit"; the corrected
            page content produced by the reviewer.
    """

    decision: str  # constrained to review decision values in Phase 4
    edited_content: str | None = None


class PageReviewResponse(BaseModel):
    """Confirmation of a recorded review decision (stub in Phase 0)."""

    page_id: int
    decision: str
    next_status: PageStatus