"""Token usage API routes — Phase 10 (FR-33, FR-34, NFR-29, NFR-30).

Provides per-query, per-page, and aggregate views into the TokenUsage data
recorded during LLM Review (Phase 5), RAG queries (Phase 7), and Raw Mode
queries (Phase 8).

Every endpoint enforces per-user isolation (FR-3 / NFR-21) at the query
layer: if a ``query_id`` or ``page_id`` does not belong to the authenticated
user, the result is indistinguishable from "not found" (404).

Error handling:
    - Non-existent or another-user's query/page id -> 404
    - Unsupported ``group_by`` value -> 422
    - Empty history (brand-new user) -> zeros / empty list, never an error
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models.token_usage import TokenUsage
from app.models.user import User
from app.schemas.token_usage import (
    TokenUsageOut,
    TokenUsageSummary,
    UsageStatsResponse,
)
from app.services.usage_service import (
    get_query_usage,
    get_page_usage,
    get_summary,
)

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=list[TokenUsageOut])
def get_usage(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TokenUsageOut]:
    """List the current user's token usage records (FR-35).

    Args:
        skip: Pagination offset.
        limit: Pagination page size (max 1000).
        db: Database session.
        current_user: The authenticated user.

    Returns:
        A list of TokenUsage records, newest first.
    """
    limit = min(limit, 1000)
    rows = (
        db.query(TokenUsage)
        .filter(TokenUsage.user_id == current_user.id)
        .order_by(TokenUsage.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows


@router.get("/summary", response_model=UsageStatsResponse)
def get_usage_summary(
    group_by: str | None = Query(
        default=None,
        description="Group results: ``day`` (calendar date) or ``document`` (per document id).",
    ),
    document_id: int | None = Query(
        default=None,
        description="Optional filter — only include tokens attributable to this document.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UsageStatsResponse:
    """Aggregate token usage figures (FR-34, NFR-30).

    Without ``group_by`` returns grand totals across all TokenUsage rows.
    With ``group_by=day`` buckets by calendar date (``YYYY-MM-DD``).
    With ``group_by=document`` attributes LLM Review tokens per-document,
    and query tokens to every document that contributed context (see
    service docstring for the double-counting semantics).

    Args:
        group_by: Optional grouping dimension.
        document_id: Optional document filter.
        db: Database session.
        current_user: The authenticated user.

    Returns:
        UsageStatsResponse with grand totals and optional per-group breakdown.

    Raises:
        HTTPException 422: If ``group_by`` is not a supported value.
    """
    valid = {None, "day", "document"}
    if group_by not in valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported group_by value '{group_by}'. "
                f"Supported values: {sorted(valid - {None})}."
            ),
        )
    result = get_summary(
        db=db,
        user_id=current_user.id,
        group_by=group_by,
        document_id=document_id,
    )
    return UsageStatsResponse(**result)


@router.get("/queries/{query_id}", response_model=list[TokenUsageOut])
def get_usage_for_query(
    query_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TokenUsageOut]:
    """Token usage for a single query (FR-33).

    Args:
        query_id: The query's primary key.
        db: Database session.
        current_user: The authenticated user.

    Returns:
        List of TokenUsage records (normally one element).

    Raises:
        HTTPException 404: If the query does not exist or belongs to another
            user (per-user isolation, FR-3 / NFR-21).
    """
    usage = get_query_usage(db, current_user.id, query_id)
    if usage is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found.",
        )
    return usage


@router.get("/pages/{page_id}", response_model=list[TokenUsageOut])
def get_usage_for_page(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TokenUsageOut]:
    """Token usage for an LLM Review on a single page (FR-15).

    Args:
        page_id: The page's primary key.
        db: Database session.
        current_user: The authenticated user.

    Returns:
        List of TokenUsage records (usually 0 or 1 elements).

    Raises:
        HTTPException 404: If the page does not exist or belongs to another
            user (per-user isolation, FR-3 / NFR-21).
    """
    usage = get_page_usage(db, current_user.id, page_id)
    if usage is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_id} not found.",
        )
    return usage