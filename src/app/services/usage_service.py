"""Token Usage aggregation queries — Phase 10 (FR-33, FR-34, NFR-29, NFR-30).

Provides the read-side of the "Token Usage Tracker" component: per-query,
per-page, and aggregate views that let a user see the token counts already
recorded during LLM Review (Phase 5), RAG queries (Phase 7), and Raw Mode
queries (Phase 8).

Every function enforces per-user isolation: a caller supplies the
authenticated user's id, and rows belonging to another user are
indistinguishable from non-existent ones (404).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.enums import TokenUsageContextType
from app.models.page import Page
from app.models.query import Query as QueryModel
from app.models.token_usage import TokenUsage

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Per-operation queries
# ──────────────────────────────────────────────────────────────────────


def get_query_usage(
    db: Session,
    user_id: int,
    query_id: int,
) -> list[TokenUsage] | None:
    """Return the token-usage records for *query_id*, or None if unknown.

    ``None`` means "not found or not yours" (the caller raises 404).  The
    function returns a list (normally one element) to stay robust should a
    future change ever record multiple LLM calls per query.

    Ownership is verified by checking that the Query row exists and belongs
    to *user_id*, then joining through Answer to find the corresponding
    ``TokenUsage`` rows with ``context_type='query'``.
    """
    query = (
        db.query(QueryModel)
        .filter(QueryModel.id == query_id, QueryModel.user_id == user_id)
        .one_or_none()
    )
    if query is None:
        return None

    answer = db.query(Answer).filter(Answer.query_id == query.id).one_or_none()
    if answer is None:
        return []

    usage = (
        db.query(TokenUsage)
        .filter(
            TokenUsage.context_type == TokenUsageContextType.QUERY,
            TokenUsage.context_id == answer.id,
        )
        .all()
    )
    return usage


def get_page_usage(
    db: Session,
    user_id: int,
    page_id: int,
) -> list[TokenUsage] | None:
    """Return token-usage records for an LLM Review on *page_id*, or None.

    Ownership is verified by joining Page -> Document, which carries
    ``user_id``.  A page may have at most one LLM Review token-usage record
    (FR-16's design), but we return a list (usually 0 or 1 elements) to stay
    robust to any future retry logic.
    """
    page = (
        db.query(Page)
        .join(Document, Page.document_id == Document.id)
        .filter(Page.id == page_id, Document.user_id == user_id)
        .one_or_none()
    )
    if page is None:
        return None

    usage = (
        db.query(TokenUsage)
        .filter(
            TokenUsage.context_type == TokenUsageContextType.LLM_REVIEW,
            TokenUsage.context_id == page.id,
        )
        .all()
    )
    return usage
# ──────────────────────────────────────────────────────────────────────
# Aggregate summary
# ──────────────────────────────────────────────────────────────────────


def _grand_totals(db: Session, user_id: int) -> tuple[int, int, int]:
    """Return (total_prompt, total_completion, total_tokens) for *user_id*."""
    row = (
        db.query(
            sa_func.coalesce(sa_func.sum(TokenUsage.prompt_tokens), 0),
            sa_func.coalesce(sa_func.sum(TokenUsage.completion_tokens), 0),
            sa_func.coalesce(sa_func.sum(TokenUsage.total_tokens), 0),
        )
        .filter(TokenUsage.user_id == user_id)
        .one()
    )
    return int(row[0]), int(row[1]), int(row[2])


def _day_group_summary(
    db: Session, user_id: int, document_id: int | None = None
) -> list[tuple[str, int, int, int]]:
    """Return (day, prompt, completion, total) rows grouped by calendar date."""
    base = db.query(
        sa_func.date(TokenUsage.timestamp).label("day"),
        sa_func.coalesce(sa_func.sum(TokenUsage.prompt_tokens), 0),
        sa_func.coalesce(sa_func.sum(TokenUsage.completion_tokens), 0),
        sa_func.coalesce(sa_func.sum(TokenUsage.total_tokens), 0),
    ).filter(TokenUsage.user_id == user_id)

    if document_id is not None:
        base = _apply_document_filter(base, db, user_id, document_id)

    rows = base.group_by(sa_func.date(TokenUsage.timestamp)).order_by(
        sa_func.date(TokenUsage.timestamp)
    ).all()
    return [(str(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rows]

def _answers_traceable_to_document(
    db: Session, user_id: int, document_id: int
) -> list[int]:
    """Return Answer.id values whose tokens are attributable to *document_id*."""
    result: set[int] = set()
    # Raw Mode: source_document_ids contains document_id
    all_raw = (
        db.query(Answer.id, Answer.source_document_ids)
        .select_from(Answer)
        .join(QueryModel, Answer.query_id == QueryModel.id)
        .filter(
            QueryModel.user_id == user_id,
            QueryModel.mode == "raw",
            Answer.source_document_ids.isnot(None),
        )
        .all()
    )
    for aid, sdid in all_raw:
        if sdid and document_id in sdid:
            result.add(aid)
    # RAG Mode: source_chunk_ids -> Chunk -> Page -> Document
    all_rag = (
        db.query(Answer.id, Answer.source_chunk_ids)
        .select_from(Answer)
        .join(QueryModel, Answer.query_id == QueryModel.id)
        .filter(
            QueryModel.user_id == user_id,
            QueryModel.mode == "rag",
            Answer.source_chunk_ids.isnot(None),
        )
        .all()
    )
    for aid, scid in all_rag:
        if scid:
            m = (
                db.query(Chunk.id)
                .join(Page, Chunk.page_id == Page.id)
                .join(Document, Page.document_id == Document.id)
                .filter(Chunk.id.in_(scid), Document.id == document_id)
                .first()
            )
            if m is not None:
                result.add(aid)
    return sorted(result)


def _document_group_summary(
    db: Session, user_id: int, document_id: int | None = None
) -> list[tuple[str, int, int, int]]:
    """Return per-document (doc_id, prompt, completion, total) rows.

    DOUBLE-COUNTING WARNING
    ────────────────────────
    A RAG query that cited chunks from two different documents will have
    its tokens attributed to BOTH documents in this view.  This is
    INTENTIONAL: each document contributed content that was part of the
    cost-incurring context sent to the LLM, so its owner should see that
    cost reflected.

    The un-grouped grand total (``get_summary`` with no ``group_by``) is
    the sum of raw TokenUsage rows and does NOT double-count anything.
    The per-document view will therefore legitimately EXCEED the grand
    total when the same query's tokens appear under multiple documents.
    """
    doc_totals: dict[int, dict[str, int]] = {}

    # ── llm_review rows: TokenUsage -> Page -> Document ─────────────
    review_rows = (
        db.query(
            Document.id.label("doc_id"),
            sa_func.coalesce(sa_func.sum(TokenUsage.prompt_tokens), 0),
            sa_func.coalesce(sa_func.sum(TokenUsage.completion_tokens), 0),
            sa_func.coalesce(sa_func.sum(TokenUsage.total_tokens), 0),
        )
        .select_from(TokenUsage)
        .join(Page, TokenUsage.context_id == Page.id)
        .join(Document, Page.document_id == Document.id)
        .filter(
            TokenUsage.user_id == user_id,
            TokenUsage.context_type == TokenUsageContextType.LLM_REVIEW,
        )
    )
    if document_id is not None:
        review_rows = review_rows.filter(Document.id == document_id)
    for r in review_rows.group_by(Document.id).all():
        _accumulate(doc_totals, int(r[0]), int(r[1]), int(r[2]), int(r[3]))

    # ── query rows: TokenUsage -> Answer -> Chunk/raw-doc-ids -> Document
    query_rows = (
        db.query(
            Answer.id.label("answer_id"),
            Answer.source_chunk_ids,
            Answer.source_document_ids,
            TokenUsage.prompt_tokens,
            TokenUsage.completion_tokens,
            TokenUsage.total_tokens,
        )
        .select_from(TokenUsage)
        .join(Answer, TokenUsage.context_id == Answer.id)
        .filter(
            TokenUsage.user_id == user_id,
            TokenUsage.context_type == TokenUsageContextType.QUERY,
        )
        .all()
    )

    for row in query_rows:
        source_chunk_ids: list[int] | None = row[1]
        source_document_ids: list[int] | None = row[2]
        pt = int(row[3])
        ct = int(row[4])
        tot = int(row[5])

        doc_ids_for_answer: set[int] = set()

        if source_document_ids is not None:
            # Raw Mode: the answer records which documents were used.
            doc_ids_for_answer.update(source_document_ids)
        elif source_chunk_ids is not None:
            # RAG Mode: join through Chunk -> Page -> Document.
            if source_chunk_ids:
                chunk_rows = (
                    db.query(Document.id)
                    .select_from(Chunk)
                    .join(Page, Chunk.page_id == Page.id)
                    .join(Document, Page.document_id == Document.id)
                    .filter(Chunk.id.in_(source_chunk_ids))
                    .distinct()
                    .all()
                )
                doc_ids_for_answer.update(int(r[0]) for r in chunk_rows)

        if document_id is not None and document_id not in doc_ids_for_answer:
            continue

        for did in doc_ids_for_answer:
            _accumulate(doc_totals, did, pt, ct, tot)

    # Sort by doc id for deterministic output.
    result = [
        (str(did), v["prompt"], v["completion"], v["total"])
        for did, v in sorted(doc_totals.items())
    ]
    return result


def _accumulate(
    container: dict[int, dict[str, int]],
    doc_id: int,
    pt: int,
    ct: int,
    tot: int,
) -> None:
    """Add *pt/ct/tot* to the running totals for *doc_id*."""
    entry = container.setdefault(doc_id, {"prompt": 0, "completion": 0, "total": 0})
    entry["prompt"] += pt
    entry["completion"] += ct
    entry["total"] += tot


def get_summary(
    db: Session,
    user_id: int,
    group_by: str | None = None,
    document_id: int | None = None,
) -> dict:
    """Return aggregate token-usage figures (FR-34, NFR-30).

    Args:
        db: SQLAlchemy session.
        user_id: The authenticated user whose usage to aggregate.
        group_by: ``None`` (grand totals only), ``"day"`` (per calendar date),
            or ``"document"`` (per owning document).
        document_id: Optional filter — only include tokens attributable to
            this specific document.

    Returns:
        A dict with keys ``total_prompt_tokens``, ``total_completion_tokens``,
        ``total_tokens``, and (when grouped) ``by_group``.

    Raises:
        ValueError: If *group_by* is not one of the supported values.
    """
    valid_groups = {None, "day", "document"}
    if group_by not in valid_groups:
        raise ValueError(
            f"Unsupported group_by value '{group_by}'. "
            f"Supported values: {sorted(valid_groups - {None})}."
        )

    if document_id and not group_by:
        tp, tc, tt = _filtered_grand_totals(db, user_id, document_id)
    else:
        tp, tc, tt = _grand_totals(db, user_id)

    result: dict = {
        "total_prompt_tokens": tp,
        "total_completion_tokens": tc,
        "total_tokens": tt,
    }

    if group_by == "day":
        raw = _day_group_summary(db, user_id, document_id=document_id)
        result["by_group"] = [
            {
                "group_key": day, "total_prompt_tokens": pt,
                "total_completion_tokens": ct, "total_tokens": tot,
            }
            for day, pt, ct, tot in raw
        ]
    elif group_by == "document":
        raw = _document_group_summary(db, user_id, document_id=document_id)
        result["by_group"] = [
            {
                "group_key": doc_id, "total_prompt_tokens": pt,
                "total_completion_tokens": ct, "total_tokens": tot,
            }
            for doc_id, pt, ct, tot in raw
        ]
    else:
        result["by_group"] = []

    return result


def _apply_document_filter(base_query, db: Session, user_id: int, document_id: int):
    """Add WHERE clause to restrict *base_query* to rows traceable to *document_id*.

    Computes the ``context_id`` values (page ids for llm_review, answer ids for
    query) that belong to *document_id*, then adds an OR-filter on the query.
    If no rows match, forces an empty result via ``sa.literal(False)``.
    """
    # ── LLM_REVIEW rows: TokenUsage.context_id IN page_ids of document ─
    page_ids = [
        r[0]
        for r in db.query(Page.id)
        .join(Document, Page.document_id == Document.id)
        .filter(Document.user_id == user_id, Document.id == document_id)
        .all()
    ]

    # ── QUERY rows: TokenUsage.context_id IN answer_ids traceable to document ──
    answer_ids = _answers_traceable_to_document(db, user_id, document_id)

    clauses = []
    if page_ids:
        clauses.append(
            sa.and_(
                TokenUsage.context_type == TokenUsageContextType.LLM_REVIEW,
                TokenUsage.context_id.in_(page_ids),
            )
        )
    if answer_ids:
        clauses.append(
            sa.and_(
                TokenUsage.context_type == TokenUsageContextType.QUERY,
                TokenUsage.context_id.in_(answer_ids),
            )
        )

    if not clauses:
        return base_query.filter(sa.literal(False))
    return base_query.filter(sa.or_(*clauses))


def _filtered_grand_totals(
    db: Session, user_id: int, document_id: int
) -> tuple[int, int, int]:
    """Grand totals for rows traceable to *document_id* only.

    Reuses the per-document breakdown and sums across groups, which
    guarantees consistency between the two views.
    """
    raw = _document_group_summary(db, user_id, document_id=document_id)
    tp = sum(r[1] for r in raw)
    tc = sum(r[2] for r in raw)
    tt = sum(r[3] for r in raw)
    return tp, tc, tt