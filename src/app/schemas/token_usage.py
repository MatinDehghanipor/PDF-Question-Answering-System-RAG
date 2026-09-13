"""Pydantic schemas for token usage reports.

Mirrors :mod:`app.models.token_usage`.  ``TokenUsageOut`` is the response
shape for GET /usage (FR-35), and the aggregate response summarizes
totals per model or per day.
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
    timestamp: datetime


class TokenUsageSummary(BaseModel):
    """Aggregate token usage grouped by model."""

    model: str
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    requests: int