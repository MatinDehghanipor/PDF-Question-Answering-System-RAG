"""Query API routes — RAG Mode (Phase 7) and Raw Mode (Phase 8).

Implements the ``POST /query`` endpoint for both RAG Mode (retrieval-augmented
generation via top-k vector search + LLM answer) and Raw Mode (original PDF
sent directly to the LLM with zero preprocessing per FR-28).
"""

from __future__ import annotations

import logging

from pathlib import Path as _Path  # avoid shadowing the import
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
# ─────────────────────────────────────────────────────────────────────────────
# OD-7 size/page-limit enforcement
# ─────────────────────────────────────────────────────────────────────────────
# [WORKING DEFAULT — OD-7]: REJECT (do not silently truncate).  Checking
# the combined selected-file size and page count before sending to the LLM
# prevents silently dropping content the user assumes is fully considered.
# Truncation would be actively misleading — the LLM could respond to only
# part of the input with no indication that content was dropped.  A warning-
# only approach was rejected for the same reason.  If this proves too strict
# in practice, ``RAW_MODE_MAX_FILE_MB`` and ``RAW_MODE_MAX_PAGES`` are each
# a single config value to raise without code changes (NFR-25).


def _check_raw_mode_limits(file_sizes_mb: list[float], total_pages: int) -> None:
    """Raise 413 if OD-7 limits would be exceeded.

    Args:
        file_sizes_mb: List of file sizes in megabytes (each PDF).
        total_pages: Sum of page counts across all selected documents.

    Raises:
        HTTPException (413): If total file size or total page count exceeds
            the configured limit, with a message identifying which limit was
            hit.
    """
    total_mb = sum(file_sizes_mb)
    if total_mb > settings.RAW_MODE_MAX_FILE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Total file size ({total_mb:.1f} MB) exceeds Raw Mode maximum "
                f"({settings.RAW_MODE_MAX_FILE_MB} MB).  Please select fewer or "
                f"smaller files, or use RAG Mode instead."
            ),
        )
    if total_pages > settings.RAW_MODE_MAX_PAGES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Total page count ({total_pages}) exceeds Raw Mode maximum "
                f"({settings.RAW_MODE_MAX_PAGES} pages).  Please select fewer or "
                f"shorter files, or use RAG Mode instead."
            ),
        )

# ─────────────────────────────────────────────────────────────────────────────
# Raw Mode handler
# ─────────────────────────────────────────────────────────────────────────────


def _handle_raw_mode(
    body: QueryCreate,
    db: Session,
    current_user: User,
) -> AnswerOut:
    """Run a Raw Mode query (FR-28 through FR-33).

    Flow (UC10/SDD §6.2):
        1. Validate ``document_ids`` present and owned by the user.
        2. Apply OD-7 size/page limits across the selected files.
        3. Create a ``Query`` row with ``mode=raw`` and ``k_value=None``.
        4. Call ``call_text_llm_with_files`` (no chunking/retrieval).
        5. Create an ``Answer`` row with ``source_chunk_ids=None`` and
           ``source_document_ids=[...]``.
        6. Record token usage.
        7. Return ``AnswerOut`` with ``mode=\\"raw\\"``, source filenames only
           (no page granularity per FR-30), and token counts.

    Error handling:
        - ``document_ids`` empty or absent → 422.
        - Any document id not owned by the current user → 404 (never leak
          another user's document existence).
        - OD-7 limit exceeded → 413.
        - LLM call fails → 502; Query row persisted, no Answer row.

    Note:
        Unlike RAG Mode's UC4 precondition, Raw Mode does **not** require
        documents to be ``ready``.  Per FR-28's wording ("selected PDF file(s)"
        with no preprocessing), any non-discarded document owned by the user
        may be used.
    """
    # ── Validate document_ids ──────────────────────────────────────────
    if not body.document_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="document_ids is required when mode='raw' and must be a non-empty list.",
        )

    doc_ids = body.document_ids

    # Fetch selected documents belonging to this user (any status except
    # discarded — Raw Mode doesn't require Ready per FR-28).
    documents = (
        db.query(Document)
        .filter(
            Document.id.in_(doc_ids),
            Document.user_id == current_user.id,
            Document.status != DocumentStatus.DISCARDED,
        )
        .all()
    )

    if len(documents) != len(doc_ids):
        found_ids = {d.id for d in documents}
        missing = [did for did in doc_ids if did not in found_ids]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document(s) with id(s) {missing} not found or not accessible.",
        )

    # ── OD-7 limit checks ──────────────────────────────────────────────
    file_sizes_mb: list[float] = []
    total_pages = 0
    for doc in documents:
        pdf_path = _Path(settings.FILE_STORAGE_PATH) / str(current_user.id) / f"{doc.id}.pdf"
        if not pdf_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"File for document {doc.id} ('{doc.filename}') is missing from storage.",
            )
        file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        file_sizes_mb.append(file_size_mb)
        total_pages += doc.page_count or 0

    _check_raw_mode_limits(file_sizes_mb, total_pages)

    # ── Create Query row ───────────────────────────────────────────────
    db_query = QueryModel(
        user_id=current_user.id,
        text=body.text,
        k_value=None,  # No retrieval in Raw Mode.
        mode=QueryMode.RAW,
    )
    db.add(db_query)
    db.flush()

    # ── Build file path list and call the LLM ──────────────────────────
    file_paths = [
        str(_Path(settings.FILE_STORAGE_PATH) / str(current_user.id) / f"{doc.id}.pdf")
        for doc in documents
    ]

    try:
        llm_result = llm_svc.call_text_llm_with_files(
            body.text, file_paths, settings.LLM_ANSWER_MODEL
        )
    except Exception as exc:
        logger.error("Raw Mode LLM call failed for query %d: %s", db_query.id, exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Raw Mode LLM answer generation failed: {exc}",
        )

    # ── Sources: filenames only (no page granularity in Raw Mode) ─────
    sources = [
        SourceRef(document_filename=doc.filename, page_number=0)
        for doc in documents
    ]

    source_document_ids = [doc.id for doc in documents]

    # ── Create Answer row ──────────────────────────────────────────────
    answer = Answer(
        query_id=db_query.id,
        generated_text=llm_result.text,
        source_chunk_ids=None,  # No chunks in Raw Mode.
        source_document_ids=source_document_ids,
        llm_model_version=settings.LLM_ANSWER_MODEL,
    )
    db.add(answer)
    db.flush()

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
        "Query %d answered (Raw, %d documents, prompt=%d, completion=%d).",
        db_query.id, len(documents), pt, ct,
    )

    return AnswerOut(
        id=answer.id,
        query_id=answer.query_id,
        generated_text=answer.generated_text,
        mode="raw",
        sources=sources,
        source_chunk_ids=None,
        source_document_ids=source_document_ids,
        llm_model_version=answer.llm_model_version,
        token_usage=TokenUsageOut(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
        ),
    )

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
        return _handle_raw_mode(body, db, current_user)

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
