"""Answer feedback API routes (POST implemented in Phase 9).

Implements the "Answer Feedback Store" endpoints (SDD §4): POST /feedback
persists a user's rating/comment on an answer; GET /feedback lists the
user's feedback.

STANDING RULE (applies to every route file from Phase 1 onward): every
database query that reads or writes user-owned data (Document/Page/Chunk/
Query/Answer/Feedback/TokenUsage) MUST filter by the current user's id, e.g.
``db.query(Feedback).filter(Feedback.user_id == current_user.id, ...)``, so
FR-3 / NFR-21 (per-user isolation) is always enforced at the query layer.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import BadRequestError, NotFoundError
from app.deps import get_current_user
from app.models.user import User
from app.schemas.feedback import FeedbackOut, FeedbackRequest
from app.services.feedback_service import (
    AnswerNotFoundError,
    EmptyFeedbackError,
    submit_feedback,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackOut, status_code=201)
def create_feedback(
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FeedbackOut:
    """Submit a rating and/or comment for an answer (FR-31, FR-32 — Phase 9).

    Feedback submission is entirely optional and one-way: no other endpoint
    reads it as a precondition, so a user can always keep querying without
    ever leaving feedback (NFR-28).

    Args:
        body: The answer being rated plus the rating and/or comment.
        db: Database session.
        current_user: The authenticated user who owns the answer.

    Returns:
        The persisted feedback record.

    Raises:
        HTTPException (400): Neither a rating nor a non-empty comment was
            supplied — there would be nothing to record.
        HTTPException (404): The answer does not exist or belongs to another
            user.  Both cases share one response so the endpoint cannot be used
            to discover other users' answers (FR-3 / NFR-21).
    """
    try:
        feedback = submit_feedback(
            db=db,
            user_id=current_user.id,
            answer_id=body.answer_id,
            rating=body.rating,
            comment=body.comment,
        )
    except EmptyFeedbackError as exc:
        raise BadRequestError(str(exc)) from exc
    except AnswerNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc

    db.commit()
    # ``timestamp`` is a server-side default, so the row must be re-read before
    # it can be serialised into FeedbackOut.
    db.refresh(feedback)
    return FeedbackOut.model_validate(feedback)


@router.get("", response_model=list[FeedbackOut])
def list_feedback(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FeedbackOut]:
    """List the current user's feedback records.

    NOTE — this endpoint is still an inert placeholder and returns an empty
    list rather than the caller's rows.  Phase 9 specifies only
    ``POST /feedback`` (FR-31/FR-32 cover submission and persistence, not
    retrieval), and no later phase in the implementation plan owns this
    listing, so implementing it would be unrequested scope.  It is documented
    here rather than silently faked because a caller cannot currently tell an
    empty result from an unimplemented one.  It remains protected by auth, so
    it leaks nothing in the meantime.

    Requires authentication (NFR-20).  Any real implementation must filter by
    current_user.id so one user can never see another user's feedback (FR-3).

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session (unused by the placeholder).
        current_user: The authenticated user whose feedback would be returned.

    Returns:
        An empty list.
    """
    return []