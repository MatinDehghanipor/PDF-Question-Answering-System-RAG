"""Token usage API routes (Phase 0 stubs wired for auth in Phase 1).

Implements the "Token Usage Tracker" endpoints (SDD §4): GET /usage returns
the current user's token consumption records and per-model aggregates.  Real
calculation/persistence arrives in Phase 10, but authentication is already
wired in so later phases never have to retrofit it.

STANDING RULE (applies to every route file from Phase 1 onward): every
database query that reads or writes user-owned data (Document/Page/Chunk/
Query/Answer/Feedback/TokenUsage) MUST filter by the current user's id, e.g.
``db.query(TokenUsage).filter(TokenUsage.user_id == current_user.id, ...)``,
so FR-3 / NFR-21 (per-user isolation) is always enforced at the query layer.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.token_usage import TokenUsageOut, TokenUsageSummary

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=list[TokenUsageOut])
def get_usage(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TokenUsageOut]:
    """List the current user's token usage records (FR-35 — Phase 10).

    Requires authentication (NFR-20).  The Phase-10 query must filter by
    current_user.id so one user can never see another user's usage (FR-3).

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session (unused by the stub).
        current_user: The authenticated user whose usage is returned.

    Returns:
        A stub (empty) list.
    """
    # TODO(Phase 10): query TokenUsage rows filtered by current_user.id.
    return []


@router.get("/summary", response_model=list[TokenUsageSummary])
def get_usage_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TokenUsageSummary]:
    """Summarize the current user's token usage per model (FR-35 — Phase 10).

    Requires authentication (NFR-20).  The Phase-10 aggregation must GROUP BY
    model over the current user's TokenUsage rows only (current_user.id), so
    one user can never see another user's aggregates (FR-3).

    Args:
        db: Database session (unused by the stub).
        current_user: The authenticated user whose summary is returned.

    Returns:
        A stub (empty) summary.
    """
    # TODO(Phase 10): GROUP BY model over the user's TokenUsage rows, filtered
    # by current_user.id.
    return []