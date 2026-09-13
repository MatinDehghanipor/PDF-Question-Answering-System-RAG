"""Pydantic schemas for the query endpoint (RAG and Raw modes).

Mirrors :mod:`app.models.query`.  Shapes for POST /query — the core QA
endpoint that will realize FR-24 (RAG) and FR-26 (Raw Mode) in Phases 7/8.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import QueryMode


class QueryCreate(BaseModel):
    """Request body for POST /query.

    Attributes:
        text: The natural-language question.
        mode: rag (default) or raw.
        k_value: Optional top-k override; validated against
            settings.MIN_TOP_K/MAX_TOP_K in Phase 7.
    """

    text: str = Field(min_length=1)
    mode: QueryMode = QueryMode.RAG
    k_value: int | None = Field(default=None, ge=1)


class QueryOut(BaseModel):
    """Record of a stored query."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    text: str
    timestamp: datetime
    k_value: int | None = None
    mode: QueryMode