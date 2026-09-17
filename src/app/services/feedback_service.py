"""Answer Feedback service — real implementation (Phase 9).

Implements the "Answer Feedback Store" component's write path (SDD §4, §2.3):
``submit_feedback`` persists an optional rating and/or optional comment on a
specific answer, linked to the originating query (FR-31, FR-32).

FR-32's "linked to the originating query, answer, mode used, and chunks used
(if RAG Mode)" is satisfied through the existing relationships rather than new
columns — see :class:`app.models.feedback.Feedback` for the reasoning.

Submission is strictly additive and never gates anything else (NFR-28: the
feedback step "shall never block the user"): no endpoint in this system reads a
``Feedback`` row to decide whether a later action is allowed.
"""

import logging

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.enums import FeedbackRating
from app.models.feedback import Feedback
from app.models.query import Query

logger = logging.getLogger(__name__)


class AnswerNotFoundError(LookupError):
    """The answer does not exist, or does not belong to the requesting user.

    Deliberately a single error for both cases so a caller cannot use this
    endpoint to probe for the existence of another user's answers
    (FR-3 / NFR-21).
    """


class EmptyFeedbackError(ValueError):
    """Neither a rating nor a non-empty comment was supplied."""


def submit_feedback(
    db: Session,
    user_id: int,
    answer_id: int,
    rating: FeedbackRating | None = None,
    comment: str | None = None,
) -> Feedback:
    """Persist feedback on one answer (FR-31, FR-32, UC9).

    Args:
        db: SQLAlchemy session.
        user_id: The authenticated user's id.  The answer's query must belong
            to this user.
        answer_id: The answer being rated.
        rating: ``positive``/``negative``, or ``None``.
        comment: Free-text comment, or ``None``.

    Returns:
        The created ``Feedback`` ORM object (flushed, not committed — the
        caller commits the transaction).

    Raises:
        EmptyFeedbackError: If neither a rating nor a non-empty comment was
            given — there would be nothing to record.
        AnswerNotFoundError: If no answer with that id belongs to ``user_id``.

    Note:
        Multiple submissions per answer are intentionally allowed (no
        uniqueness constraint): a user may change their mind, and UC9 is
        "optional" feedback rather than a single authoritative vote.  Each
        submission is a new row, so an accuracy-preserving reading of history is
        possible later; any future feedback analytics would have to decide
        explicitly whether to use the most recent row or all rows — the SRS asks
        only for submission and persistence (FR-31/FR-32), not a statistics
        view, so that choice is deliberately left open.
    """
    # Normalise the comment: ``None`` and whitespace-only both mean "absent",
    # while an explicit "" alongside a rating must not turn into a stored row
    # of empty text (FR-31's "optional free-text comment").
    normalized_comment: str | None = None
    if comment is not None:
        stripped = comment.strip()
        if stripped:
            normalized_comment = stripped

    if rating is None and normalized_comment is None:
        raise EmptyFeedbackError(
            "Feedback must include a rating and/or a non-empty comment."
        )

    # Ownership is verified by joining through the query, which is the row that
    # actually carries user_id (FR-3 / NFR-21).  Filtering here — rather than
    # fetching the answer first and comparing afterwards — means another user's
    # answer is indistinguishable from a non-existent one.
    answer = (
        db.query(Answer)
        .join(Query, Answer.query_id == Query.id)
        .filter(Answer.id == answer_id, Query.user_id == user_id)
        .one_or_none()
    )
    if answer is None:
        raise AnswerNotFoundError(
            f"Answer with id {answer_id} not found or not accessible."
        )

    feedback = Feedback(
        query_id=answer.query_id,
        answer_id=answer.id,
        rating=rating,
        comment=normalized_comment,
    )
    db.add(feedback)
    db.flush()

    logger.info(
        "Feedback %d recorded for answer %d (query %d, rating=%s, comment=%s).",
        feedback.id,
        answer.id,
        answer.query_id,
        rating.value if rating is not None else "none",
        "yes" if normalized_comment is not None else "no",
    )
    return feedback