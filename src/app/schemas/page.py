"""Pydantic schemas for the page review endpoints (Phase 4).

Mirrors :mod:`app.models.page`.  Shapes for GET/DELETE /pages/{id}/review —
the backend sends extracted page content for human review, and the client
returns an approve/reject decision (FR-6..FR-12, Phase 4).
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ChunkReviewStatus, ChunkType, ExtractionMethod, PageStatus
from app.schemas.chunk import ChunkOut


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
    review_note: str | None = None
    updated_at: datetime


class PageWithChunksOut(PageOut):
    """Page detail including its extracted chunks for the review UI (NFR-27)."""

    chunks: list[ChunkOut] = []


class PageReviewRequest(BaseModel):
    """Human review decision body for POST /pages/{id}/review.

    Attributes:
        decision: ``approved`` or ``unsatisfied``.
        note: Optional free-text note from the reviewer.  Per OD-14 default,
            this is **optional** so the action remains a simple one-click
            "Unsatisfied" button; when present, Phase 5's LLM Review prompt
            will incorporate it as extra guidance.
    """

    decision: Literal["approved", "unsatisfied"] = Field(
        ...,
        description="Review decision: 'approved' accepts the page content; "
                    "'unsatisfied' rejects it, triggering escalation.",
    )
    note: Optional[str] = Field(
        None,
        description="Optional free-text note (OD-14).  Stored on the Page "
                    "row and passed to LLM Review in Phase 5.",
    )


class PageReviewResponse(BaseModel):
    """Confirmation of a recorded review decision."""

    page_id: int
    decision: str
    next_status: PageStatus
    note: str | None = None


class ApproveAllResponse(BaseModel):
    """Confirmation of an Approve-All action (FR-13, NFR-11)."""

    document_id: int
    pages_approved: int
    message: str


class ChunkEditRequest(BaseModel):
    """Request body for PATCH /chunks/{chunk_id}.

    Only ``text`` (for text/table chunks) and ``excluded`` (boolean,
    any chunk type) can be changed.  The chunk type is immutable after
    extraction.
    """

    text: Optional[str] = Field(
        None,
        description="New text content for text or table chunks.  Setting this "
                    "triggers ``review_status = edited``.",
    )
    excluded: Optional[bool] = Field(
        None,
        description="Set to ``true`` to mark this chunk as excluded from "
                    "indexing.  Once excluded, the chunk's review_status "
                    "becomes ``rejected`` upon the next approval.",
    )