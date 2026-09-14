"""Query API routes — RAG Mode (Phase 7).

Implements the ``POST /query`` endpoint for RAG Mode (retrieval-augmented
generation via top-k vector search + LLM answer).  Raw Mode will be added
in Phase 8.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.deps import get_current_user
from app.models.answer import Answer
from app.models.document import Document
from app.models.enums import DocumentStatus, QueryMode, TokenUsageContextType
from app.models.query import Query as QueryModel
from app.models.user import User
from app.schemas.answer import AnswerOut, SourceRef, TokenUsageOut
from app.schemas.query import QueryCreate
from app.services import llm_service as llm_svc
from app.services.prompt_builder import build_rag_prompt
from app.services.retrieval_service import retrieve_top_k
from app.services.token_tracker import record_token_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=AnswerOut)
def ask_question(
    body: QueryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnswerOut:
    """Answer a natural-language question in RAG Mode (FR-24 through FR-33).

    RAG Mode flow (UC4/SDD §6.2):
        1. Validate *k* and the "at least one Ready document" precondition.
        2. Create a ``Query`` row.
        3. Embed the query and retrieve top-*k* chunks (FR-25).
        4. Reassemble chunks in reading order per OD-6 (FR-26).
        5. Build a grounded prompt per OD-10 (FR-27).
        6. Send to the LLM and receive answer + token usage (FR-33).
        7. Create an ``Answer`` row and record token usage.
        8. Return ``AnswerOut`` with ``mode="rag"``, deduplicated source
           references, and token counts.

    Error handling:
        - No Ready documents → 400 (UC4 precondition unmet).
        - ``k`` outside ``[MIN_TOP_K, MAX_TOP_K]`` → 422.
        - LLM call fails (timeout, rate limit) → 502; the Query row is
          still persisted but no Answer row is created.
        - Empty retrieval (narrow query) → still calls the LLM with an
          explicit note that no excerpts matched, per OD-10's grounding rule.

    Args:
        body: The question string, optional *k* override, and mode selector.
        db: SQLAlchemy session.
        current_user: The authenticated user (scopes all queries per NFR-21).

    Returns:
        An ``AnswerOut`` with the generated text, mode flag, sources, and
        token usage.
    """
    # ── Resolve k ──────────────────────────────────────────────────────
    k_value = body.k_value if body.k_value is not None else settings.DEFAULT_TOP_K
    if k_value < settings.MIN_TOP_K or k_value > settings.MAX_TOP_K:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"k_value must be between {settings.MIN_TOP_K} and {settings.MAX_TOP_K} "
                   f"(got {k_value}).",
        )

    # ── Mode dispatch ──────────────────────────────────────────────────
    if body.mode == QueryMode.RAW:
        # Raw Mode is Phase 8.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Raw Mode is not yet implemented (Phase 8).",
        )

    # ── UC4 precondition: at least one Ready document ──────────────────
    ready_count = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.status == DocumentStatus.READY,
        )
        .count()
    )
    if ready_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Ready documents found. Please upload and get at least one "
                   "document fully approved before asking a question.",
        )

    # ── Create Query row ───────────────────────────────────────────────
    db_query = QueryModel(
        user_id=current_user.id,
        text=body.text,
        k_value=k_value,
        mode=QueryMode.RAG,
    )
    db.add(db_query)
    db.flush()  # get db_query.id

    # ── Retrieve top-k chunks ──────────────────────────────────────────
    try:
        retrieved = retrieve_top_k(current_user.id, body.text, k_value)
    except Exception as exc:
        logger.error("Retrieval failed for user %d: %s", current_user.id, exc)
        # Query row is persisted, but we cannot answer.
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Vector search failed: {exc}",
        )

    # ── Build prompt ───────────────────────────────────────────────────
    prompt = build_rag_prompt(body.text, retrieved)

    # ── Call the answering LLM ─────────────────────────────────────────
    try:
        llm_result = llm_svc.call_text_llm(prompt, settings.LLM_ANSWER_MODEL)
    except Exception as exc:
        logger.error("LLM call failed for query %d: %s", db_query.id, exc)
        # Query row is persisted (so usage history is not lost), but no
        # Answer row is created for a failed call.
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM answer generation failed: {exc}",
        )

    # ── Deduplicate sources (FR-30) ────────────────────────────────────
    seen: set[tuple[str, int]] = set()
    sources: list[SourceRef] = []
    for rc in retrieved:
        key = (rc.document_filename, rc.page_number)
        if key not in seen:
            seen.add(key)
            sources.append(SourceRef(
                document_filename=rc.document_filename,
                page_number=rc.page_number,
            ))

    # ── Record source_chunk_ids (the order used in the prompt) ─────────
    source_chunk_ids = [int(rc.chunk_id.split("_")[1]) for rc in retrieved
                        if rc.chunk_id.startswith("chunk_")]

    # ── Create Answer row ──────────────────────────────────────────────
    answer = Answer(
        query_id=db_query.id,
        generated_text=llm_result.text,
        source_chunk_ids=source_chunk_ids if source_chunk_ids else None,
        llm_model_version=settings.LLM_ANSWER_MODEL,
    )
    db.add(answer)
    db.flush()  # get answer.id

    # ── Record token usage (FR-33) ─────────────────────────────────────
    pt = llm_result.prompt_tokens or 0
    ct = llm_result.completion_tokens or 0
    record_token_usage(
        db=db,
        user_id=current_user.id,
        context_type=TokenUsageContextType.QUERY,
        context_id=answer.id,
        model_used=settings.LLM_ANSWER_MODEL,
        prompt_tokens=pt,
        completion_tokens=ct,
    )

    db.commit()
    db.refresh(answer)

    logger.info(
        "Query %d answered (RAG, k=%d, %d sources, prompt=%d, completion=%d).",
        db_query.id, k_value, len(sources), pt, ct,
    )

    return AnswerOut(
        id=answer.id,
        query_id=answer.query_id,
        generated_text=answer.generated_text,
        mode="rag",
        sources=sources,
        source_chunk_ids=answer.source_chunk_ids,
        llm_model_version=answer.llm_model_version,
        token_usage=TokenUsageOut(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
        ),
    )
