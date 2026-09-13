"""Page review API routes (Phase 0 stubs wired for auth in Phase 1).

Implements the human-review gate of the "Document and Page Registry"
component (SDD §4): the backend exposes an extracted page's content for
review (GET) and records the reviewer's approve/edit/reject decision (POST).
Real review-decision logic arrives in Phase 4, but authentication is already
wired in so later phases never have to retrofit it.

STANDING RULE (applies to every route file from Phase 1 onward): every
database query that reads or writes user-owned data (Document/Page/Chunk/
Query/Answer/Feedback/TokenUsage) MUST filter by the current user's id, e.g.
``db.query(Page).filter(Page.document.has(user_id=current_user.id), ...)``, so
FR-3 / NFR-21 (per-user isolation) is always enforced at the query layer.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models.enums import PageStatus
from app.models.user import User
from app.schemas.page import PageOut, PageReviewRequest, PageReviewResponse

router = APIRouter(prefix="/pages", tags=["pages"])


@router.get("/{page_id}/review", response_model=PageOut)
def get_page_for_review(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageOut:
    """Fetch a page's extracted content and state for human review (FR-6 — Phase 4).

    Requires authentication (NFR-20).  Phase 4 must load the page through a
    query scoped to the current user (Page → Document.user_id ==
    current_user.id) so a user can never review another user's page (FR-3).

    Args:
        page_id: ID of the page awaiting feedback.
        db: Database session (unused by the stub).
        current_user: The authenticated user (ownership check target).

    Returns:
        A stub page record.
    """
    # TODO(Phase 4): load the page from the registry with its chunks and
    # extraction metadata; enforce owner access via Document.user_id ==
    # current_user.id (NFR-21).
    return PageOut(id=page_id, document_id=1, page_number=1,
                   status=PageStatus.AWAITING_FEEDBACK, extraction_method=None,
                   quality_score=None, review_round=1, updated_at=datetime.utcnow())


@router.post("/{page_id}/review", response_model=PageReviewResponse)
def submit_page_review(
    page_id: int,
    body: PageReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageReviewResponse:
    """Record a human review decision (FR-7..FR-12 — Phase 4).

    Requires authentication (NFR-20).  Phase 4 must verify the page belongs to
    the current user before applying status transitions (FR-3).

    Args:
        page_id: ID of the page being reviewed.
        body: The review decision and optional edited content.
        db: Database session (unused by the stub).
        current_user: The authenticated user (ownership check target).

    Returns:
        A stub review confirmation with the resulting page status.
    """
    # TODO(Phase 4): verify page ownership through the current user's document,
    # apply status transitions, spawn LLM Review on reject, and route approved
    # pages toward chunking.
    return PageReviewResponse(page_id=page_id, decision=body.decision,
                              next_status=PageStatus.APPROVED)