"""Answer feedback API routes (Phase 0 stubs).

Implements the "Answer Feedback Store" endpoints (SDD §4): POST /feedback
persists a user's rating/comment on an answer; GET /feedback lists the
user's feedback.  Real persistence logic arrives in Phase 9.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.feedback import FeedbackCreate, FeedbackOut

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackOut, status_code=201)
def create_feedback(body: FeedbackCreate, db: Session = Depends(get_db)) -> FeedbackOut:
    """Submit a rating and optional comment for an answer.

    Realizes FR-28 and FR-29 (rate/comment on answers) — see Phase 9.

    Args:
        body: The query/answer being rated plus the rating and comment.
        db: Database session (unused by the stub).

    Returns:
        A stub feedback record.
    """
    # TODO(Phase 9): persist a Feedback row linked to the query/answer and
    # enforce that the user owns the query (NFR-21).
    return FeedbackOut(
        id=1, query_id=body.query_id, answer_id=body.answer_id,
        rating=body.rating, comment=body.comment, timestamp=datetime.utcnow(),
    )


@router.get("", response_model=list[FeedbackOut])
def list_feedback(skip: int = 0, limit: int = 50,
                  db: Session = Depends(get_db)) -> list[FeedbackOut]:
    """List the current user's feedback records.

    Realizes FR-30 (view feedback history) — see Phase 9.

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session (unused by the stub).

    Returns:
        A stub (empty) list.
    """
    # TODO(Phase 9): query Feedback rows filtered by the authenticated user.
    return []