"""Pydantic schemas for token usage reports.

Mirrors :mod:`app.models.token_usage`.  ``TokenUsageOut`` is the response
shape for GET /usage (FR-35), and the aggregate response summarizes
totals per model or per day.

Extended in Phase 10:
    - ``is_estimated`` surfaced on ``TokenUsageOut`` so a user/developer can
      tell which figures are provider-reported vs. locally estimated.
    - ``UsageStatsResponse`` and ``GroupedUsageItem`` for the summary
      endpoint's aggregate view (FR-34 / NFR-30).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import TokenUsageContextType


class TokenUsageOut(BaseModel):
    """A single token usage record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    context_type: TokenUsageContextType
    context_id: int
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    is_estimated: bool = False
    timestamp: datetime


class TokenUsageSummary(BaseModel):
    """Aggregate token usage grouped by model."""

    model: str
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    requests: int


class GroupedUsageItem(BaseModel):
    """One group in the summary breakdown (Phase 10).

    Attributes:
        group_key: The day (``YYYY-MM-DD``) or document id (as string) that
            this item aggregates over.
        total_prompt_tokens: Sum of prompt tokens in this group.
        total_completion_tokens: Sum of completion tokens in this group.
        total_tokens: Sum of total_tokens in this group.
    """

    group_key: str
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int


class UsageStatsResponse(BaseModel):
    """Grand totals with optional per-group breakdown (Phase 10, FR-34).

    Attributes:
        total_prompt_tokens: Sum of prompt_tokens across all matching rows.
        total_completion_tokens: Sum of completion_tokens across all matching
            rows.
        total_tokens: Sum of total_tokens across all matching rows.
        by_group: Per-group breakdown when ``group_by`` was requested.
            Empty list when no grouping is applied.
    """

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    by_group: list[GroupedUsageItem] = []