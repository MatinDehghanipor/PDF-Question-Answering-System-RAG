"""Page review API routes (Phase 0 stubs).

Implements the human-review gate of the "Document and Page Registry"
component (SDD §4): the backend exposes an extracted page's content for
review (GET) and records the reviewer's approve/edit/reject decision (POST).
Real review-decision logic arrives in Phase 4.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import PageStatus
from app.schemas.page import PageOut, PageReviewRequest, PageReviewResponse

router = APIRouter(prefix="/pages", tags=["pages"])


@router.get("/{page_id}/review", response_model=PageOut)
def get_page_for_review(page_id: int, db: Session = Depends(get_db)) -> PageOut:
    """Fetch a page's extracted content and state for human review.

    Realizes FR-6 (fetch page for review) — see Phase 4.

    Args:
        page_id: ID of the page awaiting feedback.
        db: Database session (unused by the stub).

    Returns:
        A stub page record.
    """
    # TODO(Phase 4): load the page from the registry with its chunks and
    # extraction metadata; enforce owner access (NFR-21).
    return PageOut(id=page_id, document_id=1, page_number=1,
                   status=PageStatus.AWAITING_FEEDBACK, extraction_method=None,
                   quality_score=None, review_round=1, updated_at=datetime.utcnow())


@router.post("/{page_id}/review", response_model=PageReviewResponse)
def submit_page_review(page_id: int, body: PageReviewRequest,
                       db: Session = Depends(get_db)) -> PageReviewResponse:
    """Record a human review decision (approve / edit / reject) for a page.

    Realizes FR-7..FR-12 (approve / edit / reject flow) — see Phase 4.

    Args:
        page_id: ID of the page being reviewed.
        body: The review decision and optional edited content.
        db: Database session (unused by the stub).

    Returns:
        A stub review confirmation with the resulting page status.
    """
    # TODO(Phase 4): apply status transitions, spawn LLM Review on reject,
    # and route approved pages toward chunking.
    return PageReviewResponse(page_id=page_id, decision=body.decision,
                              next_status=PageStatus.APPROVED)