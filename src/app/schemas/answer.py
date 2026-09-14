"""Pydantic schemas for answers.

Mirrors :mod:`app.models.answer`.  ``AnswerOut`` is the response body for
POST /query (both RAG and Raw modes).  ``source_chunk_ids`` is None for
Raw Mode answers.

Extended in Phase 7: adds ``mode`` (FR-29), ``sources`` (FR-30), and
``token_usage`` (FR-33).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class SourceRef(BaseModel):
    """A single source reference in an answer (FR-30).

    Attributes:
        document_filename: Original filename of the source document.
        page_number: 1-based page number cited.
    """

    document_filename: str
    page_number: int


class TokenUsageOut(BaseModel):
    """Token consumption for a single LLM call (FR-33).

    Note:
        Embedding-token recording is not applicable for this project's chosen
        LOCAL embedding model (sentence-transformers / all-MiniLM-L6-v2).  If
        the embedding model is later swapped for an API-based one, a fourth
        field ``embedding_tokens`` should be added here and populated by
        ``retrieval_service.retrieve_top_k``.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AnswerOut(BaseModel):
    """Public representation of a generated answer.

    Attributes:
        id: Answer primary key.
        query_id: The query this answers.
        generated_text: The LLM-generated answer text.
        mode: ``rag`` or ``raw`` — which mode produced this answer (FR-29).
        sources: Deduplicated list of (document, page) references used
            (FR-30).  Empty for Raw Mode.
        source_chunk_ids: Ordered list of chunk ids used as RAG context;
            None for Raw Mode.
        llm_model_version: Model that produced the answer.
        token_usage: Token counts for the LLM call (FR-33); None if the
            call failed or usage data was unavailable.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    query_id: int
    generated_text: str
    mode: str = "rag"
    sources: List[SourceRef] = []
    source_chunk_ids: Optional[List[int]] = None
    llm_model_version: str
    token_usage: Optional[TokenUsageOut] = None
