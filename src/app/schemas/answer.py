"""Pydantic schemas for answers.

Mirrors :mod:`app.models.answer`.  ``AnswerOut`` is the response body for
POST /query (both RAG and Raw modes).  ``source_chunk_ids`` is None for
Raw Mode answers.
"""

from pydantic import BaseModel, ConfigDict


class AnswerOut(BaseModel):
    """Public representation of a generated answer.

    Attributes:
        id: Answer primary key.
        query_id: The query this answers.
        generated_text: The LLM-generated answer text.
        source_chunk_ids: Ordered list of chunk ids used as RAG context;
            None for Raw Mode.
        llm_model_version: Model that produced the answer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    query_id: int
    generated_text: str
    source_chunk_ids: list[int] | None = None
    llm_model_version: str