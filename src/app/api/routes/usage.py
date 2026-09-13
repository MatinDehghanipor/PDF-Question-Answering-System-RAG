"""Token usage API routes (Phase 0 stubs).

Implements the "Token Usage Tracker" endpoints (SDD §4): GET /usage returns
the current user's token consumption records and per-model aggregates.  Real
calculation/persistence arrives in Phase 10.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.token_usage import TokenUsageOut, TokenUsageSummary

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=list[TokenUsageOut])
def get_usage(skip: int = 0, limit: int = 100,
              db: Session = Depends(get_db)) -> list[TokenUsageOut]:
    """List the current user's token usage records.

    Realizes FR-35 (view token usage) — see Phase 10.

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session (unused by the stub).

    Returns:
        A stub (empty) list.
    """
    # TODO(Phase 10): query TokenUsage rows filtered by the authenticated user.
    return []


@router.get("/summary", response_model=list[TokenUsageSummary])
def get_usage_summary(db: Session = Depends(get_db)) -> list[TokenUsageSummary]:
    """Summarize the current user's token usage per model.

    Realizes FR-35 (aggregate token usage) — see Phase 10.

    Args:
        db: Database session (unused by the stub).

    Returns:
        A stub (empty) summary.
    """
    # TODO(Phase 10): GROUP BY model over the user's TokenUsage rows.
    return []