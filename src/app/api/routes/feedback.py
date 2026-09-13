"""Answer feedback API routes (Phase 0 stubs wired for auth in Phase 1).

Implements the "Answer Feedback Store" endpoints (SDD §4): POST /feedback
persists a user's rating/comment on an answer; GET /feedback lists the
user's feedback.  Real persistence logic arrives in Phase 9, but
authentication is already wired in so later phases never have to retrofit it.

STANDING RULE (applies to every route file from Phase 1 onward): every
database query that reads or writes user-owned data (Document/Page/Chunk/
Query/Answer/Feedback/TokenUsage) MUST filter by the current user's id, e.g.
``db.query(Feedback).filter(Feedback.user_id == current_user.id, ...)``, so
FR-3 / NFR-21 (per-user isolation) is always enforced at the query layer.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.feedback import FeedbackCreate, FeedbackOut

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackOut, status_code=201)
def create_feedback(
    body: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FeedbackOut:
    """Submit a rating and optional comment for an answer (FR-28/FR-29 — Phase 9).

    Requires authentication (NFR-20).  Phase 9 must verify the current user
    owns the query/answer being rated (via Query.user_id == current_user.id)
    and persist the Feedback row scoped to current_user.id (FR-3).

    Args:
        body: The query/answer being rated plus the rating and comment.
        db: Database session (unused by the stub).
        current_user: The authenticated user who owns the feedback.

    Returns:
        A stub feedback record.
    """
    # TODO(Phase 9): persist a Feedback row linked to the query/answer and
    # enforce that the user owns the query (NFR-21).  All Feedback reads and
    # writes must filter by current_user.id.
    return FeedbackOut(
        id=1, query_id=body.query_id, answer_id=body.answer_id,
        rating=body.rating, comment=body.comment, timestamp=datetime.utcnow(),
    )


@router.get("", response_model=list[FeedbackOut])
def list_feedback(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FeedbackOut]:
    """List the current user's feedback records (FR-30 — Phase 9).

    Requires authentication (NFR-20).  The Phase-9 query must filter by
    current_user.id so one user can never see another user's feedback (FR-3).

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session (unused by the stub).
        current_user: The authenticated user whose feedback is returned.

    Returns:
        A stub (empty) list.
    """
    # TODO(Phase 9): query Feedback rows filtered by current_user.id.
    return []