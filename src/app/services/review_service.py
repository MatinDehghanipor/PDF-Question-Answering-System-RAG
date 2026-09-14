"""Review service — page approval, unsatisfied, and approve-all logic (Phase 4).

Implements the human-review decision logic for the "Document and Page Registry"
component (SDD §4): ``approve_page``, ``mark_unsatisfied``, and
``approve_all_pending`` drive the page/document status machine per the SDD §6.1
activity diagram.

Approving a page sets its non-excluded chunks to ``approved``/``edited``,
calls the (stubbed) ``enqueue_for_indexing``, and checks whether the whole
document can be marked ``ready``.

Marking a page unsatisfied stores the optional review note (OD-14 default),
sets status to ``llm_review`` (or discards the document on Round-2 rejection),
and calls the (stubbed) ``trigger_llm_review``.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.enums import (
    ChunkReviewStatus,
    DocumentStatus,
    PageStatus,
)
from app.models.page import Page

logger = logging.getLogger(__name__)


def approve_page(page: Page, db: Session) -> None:
    """Approve a single page's content.

    Sets status to ``approved``, marks all non-excluded chunks as
    ``approved`` (edited chunks keep ``edited``), rejects excluded chunks,
    calls the stub ``enqueue_for_indexing``, and checks if the entire
    document can be marked ``ready``.

    Args:
        page: The Page row (must be in ``awaiting_feedback`` status).
        db: SQLAlchemy session (caller commits the transaction).

    Raises:
        ValueError: If the page is not in ``awaiting_feedback`` status.
    """
    if page.status != PageStatus.AWAITING_FEEDBACK:
        raise ValueError(
            f"Cannot approve page {page.id}: status is '{page.status.value}', "
            f"expected 'awaiting_feedback'."
        )

    now = datetime.utcnow()

    for chunk in page.chunks:
        if chunk.review_status == ChunkReviewStatus.REJECTED:
            continue
        if chunk.review_status == ChunkReviewStatus.EDITED:
            pass  # keep as edited (counts as "approved/edited" per FR-17)
        else:
            chunk.review_status = ChunkReviewStatus.APPROVED
        chunk.reviewed_at = now

    page.status = PageStatus.APPROVED
    page.updated_at = now
    db.flush()

    # Stub: inform the chunker (Phase 6).
    _stub_enqueue_for_indexing(page.id)

    # Check if the entire document is now ready.
    _update_document_status_if_ready(page.document, db)
def mark_unsatisfied(
    page: Page,
    db: Session,
    note: str | None = None,
) -> None:
    """Mark a page as unsatisfactory and escalate (Round 1) or discard (Round 2).

    - **Round 1** (``review_round == 1``): stores the optional note, sets
      status to ``llm_review``, calls the stub ``trigger_llm_review``.
    - **Round 2** (``review_round == 2``): the user has already had one LLM
      Review attempt and is still unsatisfied — discards the **entire
      document** per FR-17 and SDD §2.1 step 6.

    Args:
        page: The Page row (must be in ``awaiting_feedback``).
        db: SQLAlchemy session.
        note: Optional free-text note (OD-14 default).

    Raises:
        ValueError: If the page is not in ``awaiting_feedback``.
    """
    if page.status != PageStatus.AWAITING_FEEDBACK:
        raise ValueError(
            f"Cannot mark page {page.id} unsatisfied: status is "
            f"'{page.status.value}', expected 'awaiting_feedback'."
        )

    page.review_note = note

    if page.review_round == 2:
        logger.warning("Page %d rejected in Round 2 — discarding document %d.", page.id, page.document_id)
        page.status = PageStatus.DISCARDED
        doc = page.document
        doc.status = DocumentStatus.DISCARDED
        db.flush()
        logger.info("Document %d discarded due to Round-2 rejection of page %d.", doc.id, page.id)
    else:
        page.status = PageStatus.LLM_REVIEW
        page.updated_at = datetime.utcnow()
        db.flush()
        _stub_trigger_llm_review(page.id, note)


def approve_all_pending(document: Document, db: Session) -> int:
    """Approve every page of *document* that is currently ``awaiting_feedback``.

    Operates in a single transaction (NFR-11); the caller commits.

    Returns:
        The number of pages approved (0 if none were pending).
    """
    pending_pages = [p for p in document.pages if p.status == PageStatus.AWAITING_FEEDBACK]
    for page in pending_pages:
        approve_page(page, db)
    if not pending_pages:
        logger.info("Approve-All on document %d: zero pending pages.", document.id)
    else:
        logger.info("Approve-All approved %d page(s) for document %d.", len(pending_pages), document.id)
    return len(pending_pages)


# ──────────────────────────────────────────────────────────────────────
# Internal stubs (top-down: called now, filled in later phases)
# ──────────────────────────────────────────────────────────────────────


def _stub_enqueue_for_indexing(page_id: int) -> None:
    """Stub: enqueue an approved page for chunking/embedding/indexing (Phase 6)."""
    logger.info("# TODO(Phase 6): chunk, embed, and index approved chunks for page %d.", page_id)


def _stub_trigger_llm_review(page_id: int, note: str | None) -> None:
    """Stub: trigger LLM Review for a Round-1 rejected page (Phase 5)."""
    logger.info("# TODO(Phase 5): render page %d as image, call vision LLM with note '%s'.", page_id, note)


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _update_document_status_if_ready(document: Document, db: Session) -> None:
    """If every active page is approved, mark the document ``ready``."""
    active_pages = [p for p in (document.pages or []) if p.status != PageStatus.DISCARDED]
    if active_pages and all(p.status == PageStatus.APPROVED for p in active_pages):
        document.status = DocumentStatus.READY
        logger.info("Document %d is now READY.", document.id)