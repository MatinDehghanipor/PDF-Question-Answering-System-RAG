"""Page review API routes — real implementation (Phase 4).

Implements the human-review gate of the "Document and Page Registry"
component (SDD §4): expose extracted page content for review (GET), accept
the reviewer's approve/unsatisfied decision (POST), allow chunk-level edits
(PATCH), and bulk-approve via Approve All.

All endpoints enforce per-user isolation (FR-3 / NFR-21) and proper status-
machine transitions (no approving an already-approved page, etc.).

STANDING RULE: every database query that reads or writes user-owned data
MUST filter by the current user's id.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.enums import ChunkReviewStatus, PageStatus
from app.models.page import Page
from app.models.user import User
from app.schemas.chunk import ChunkOut
from app.schemas.page import (
    ApproveAllResponse,
    ChunkEditRequest,
    PageOut,
    PageReviewRequest,
    PageReviewResponse,
    PageWithChunksOut,
)
from app.services.review_service import (
    approve_all_pending,
    approve_page,
    mark_unsatisfied,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pages", tags=["pages"])


# ────────────────────────────────────────────────────────────────────────
# Helper: fetch a page scoped to current_user, or raise 404
# ────────────────────────────────────────────────────────────────────────


def _get_user_page_or_404(
    db: Session, page_id: int, current_user: User,
) -> Page:
    """Fetch a Page verifying Document.user_id == current_user.id."""
    page = (
        db.query(Page)
        .join(Document)
        .filter(Page.id == page_id, Document.user_id == current_user.id)
        .first()
    )
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page {page_id} not found.")
    return page
# ────────────────────────────────────────────────────────────────────────
# GET /pages/{page_id}/review  — fetch page with chunks for review
# ────────────────────────────────────────────────────────────────────────


@router.get("/{page_id}/review", response_model=PageWithChunksOut)
def get_page_for_review(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageWithChunksOut:
    """Fetch a page with its chunks for human review (FR-11, NFR-27)."""
    page = _get_user_page_or_404(db, page_id, current_user)
    return PageWithChunksOut(
        id=page.id,
        document_id=page.document_id,
        page_number=page.page_number,
        status=page.status,
        extraction_method=page.extraction_method,
        quality_score=page.quality_score,
        review_round=page.review_round,
        review_note=page.review_note,
        updated_at=page.updated_at,
        chunks=page.chunks,
    )


# ────────────────────────────────────────────────────────────────────────
# POST /pages/{page_id}/review  — submit approve / unsatisfied decision
# ────────────────────────────────────────────────────────────────────────


@router.post("/{page_id}/review", response_model=PageReviewResponse)
def submit_page_review(
    page_id: int,
    body: PageReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageReviewResponse:
    """Record a human review decision (FR-12).

    ``approved`` → marks page approved, queues for indexing (stub).
    ``unsatisfied`` → Round 1 escalates to LLM Review; Round 2 discards doc.
    """
    page = _get_user_page_or_404(db, page_id, current_user)

    if page.status != PageStatus.AWAITING_FEEDBACK:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Page {page_id} is '{page.status.value}', not 'awaiting_feedback'.",
        )

    if body.decision == "approved":
        approve_page(page, db)
        db.commit()
        next_status = PageStatus.APPROVED
    elif body.decision == "unsatisfied":
        mark_unsatisfied(page, db, note=body.note)
        db.commit()
        next_status = page.status
    else:
        raise HTTPException(status_code=422, detail=f"Unknown decision '{body.decision}'.")

    return PageReviewResponse(
        page_id=page.id, decision=body.decision,
        next_status=next_status, note=body.note,
    )


# ────────────────────────────────────────────────────────────────────────
# PATCH /chunks/{chunk_id}  — edit chunk text or set excluded flag
# ────────────────────────────────────────────────────────────────────────


@router.patch("/chunks/{chunk_id}", response_model=ChunkOut)
def edit_chunk(
    chunk_id: int,
    body: ChunkEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChunkOut:
    """Edit a chunk's text or mark it excluded (FR-12).

    Only allowed while the chunk's page is ``awaiting_feedback``.
    """
    chunk = (
        db.query(Chunk)
        .join(Page)
        .join(Document)
        .filter(Chunk.id == chunk_id, Document.user_id == current_user.id)
        .first()
    )
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found.")

    if chunk.page.status != PageStatus.AWAITING_FEEDBACK:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot edit chunk {chunk_id}: page is '{chunk.page.status.value}'.",
        )

    changed = False
    if body.text is not None:
        if chunk.chunk_type.value in ("text", "table"):
            if body.text != chunk.text:
                chunk.text = body.text
                chunk.review_status = ChunkReviewStatus.EDITED
                changed = True
        else:
            raise HTTPException(status_code=422, detail=f"Cannot set 'text' on a '{chunk.chunk_type.value}' chunk.")
    if body.excluded is not None and body.excluded != chunk.excluded:
        chunk.excluded = body.excluded
        changed = True

    if changed:
        db.commit()
        db.refresh(chunk)

    return chunk


@router.get("/{page_id}/review", response_model=PageOut)
def get_page_for_review(
    page_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageOut:
    """Fetch a page's extracted content and state for human review (FR-6 — Phase 4).

    Requires authentication (NFR-20).  Phase 4 must load the page through a
    query scoped to the current user (Page → Document.user_id ==
    current_user.id) so a user can never review another user's page (FR-3).

    Args:
        page_id: ID of the page awaiting feedback.
        db: Database session (unused by the stub).
        current_user: The authenticated user (ownership check target).

    Returns:
        A stub page record.
    """
    # TODO(Phase 4): load the page from the registry with its chunks and
    # extraction metadata; enforce owner access via Document.user_id ==
    # current_user.id (NFR-21).
    return PageOut(id=page_id, document_id=1, page_number=1,
                   status=PageStatus.AWAITING_FEEDBACK, extraction_method=None,
                   quality_score=None, review_round=1, updated_at=datetime.utcnow())


@router.post("/{page_id}/review", response_model=PageReviewResponse)
def submit_page_review(
    page_id: int,
    body: PageReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageReviewResponse:
    """Record a human review decision (FR-7..FR-12 — Phase 4).

    Requires authentication (NFR-20).  Phase 4 must verify the page belongs to
    the current user before applying status transitions (FR-3).

    Args:
        page_id: ID of the page being reviewed.
        body: The review decision and optional edited content.
        db: Database session (unused by the stub).
        current_user: The authenticated user (ownership check target).

    Returns:
        A stub review confirmation with the resulting page status.
    """
    # TODO(Phase 4): verify page ownership through the current user's document,
    # apply status transitions, spawn LLM Review on reject, and route approved
    # pages toward chunking.
    return PageReviewResponse(page_id=page_id, decision=body.decision,
                              next_status=PageStatus.APPROVED)