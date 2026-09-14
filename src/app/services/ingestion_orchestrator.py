"""Ingestion Orchestrator — per-page state machine for Phase 2.

Implements the core orchestration logic of the "Document and Page Registry"
component (SDD §4): drives each page of an uploaded PDF through the initial
extraction pipeline and lands it in the "Awaiting Feedback, Round 1" state
with a placeholder chunk ready for human review.

.. admonition:: Pipeline flow (SDD §5.1 — Phase 2 skeleton)

    This module implements the **real orchestration skeleton**:

    A. Upload -> B. Validate -> D. Split -> E. For each page:
        F. ``extract_native()`` (stub, Phase 3 real)
        G. ``score_quality()`` (stub, Phase 3 real)
        H. If score < threshold -> I. ``extract_ocr()`` (stub, Phase 3 real)
        J. Set status = ``awaiting_feedback``, round 1

    The real content-extraction is still stubbed.  Real review/approve/reject
    endpoints (K->W) arrive in Phase 4 and Phase 5.

.. admonition:: FR-37 guard (OD-8 default)

    ``reprocess_document()`` raises ``NotImplementedError``.  If true
    re-upload/versioning is needed later, this is the single function to change.
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.enums import (
    ChunkReviewStatus,
    ChunkType,
    DocumentStatus,
    ExtractionMethod,
    PageStatus,
)
from app.models.page import Page
from app.services.native_extractor import ExtractionResult, extract_native
from app.services.ocr_extractor import extract_ocr
from app.services.quality_scorer import score_quality

logger = logging.getLogger(__name__)


def _process_single_page(
    db: Session,
    page: Page,
    pdf_path: str | Path,
) -> None:
    """Run the per-page extraction pipeline (SDD 5.1 steps F->G->H->I->J).

    1. Calls (stubbed) native extractor - F
    2. Calls (stubbed) quality scorer - G
    3. If quality below threshold, calls (stubbed) OCR extractor - H->I
    4. Creates a placeholder Chunk row with stub content
    5. Sets page status to awaiting_feedback, round 1 - J

    The quality-score branch (step 3) is genuine code.  In Phase 2 the stub
    scorer always returns 1.0, so the OCR branch is never triggered, but it
    is NOT dead code - Phase 3's real scorer will naturally trigger it.

    Args:
        db: SQLAlchemy session (transaction managed by caller).
        page: The Page row to process.
        pdf_path: Path to the PDF file on disk.
    """
    page.status = PageStatus.INITIAL_PROCESSING
    db.flush()

    # Step F: Native extraction (STUB - Phase 3)
    native_result: ExtractionResult = extract_native(pdf_path, page.page_number)

    # Step G: Quality scoring (STUB - Phase 3)
    quality_score: float = score_quality(native_result)
    page.quality_score = quality_score

    # Step H->I: OCR fallback (branch exists, unreachable with stub)
    if quality_score < settings.QUALITY_SCORE_THRESHOLD:
        logger.info(
            "Page %d quality score %.2f below threshold %.2f - OCR fallback.",
            page.page_number, quality_score, settings.QUALITY_SCORE_THRESHOLD,
        )
        ocr_result: ExtractionResult = extract_ocr(pdf_path, page.page_number)
        extraction_method = ExtractionMethod.OCR
        final_result = ocr_result
    else:
        extraction_method = ExtractionMethod.NATIVE
        final_result = native_result

    page.extraction_method = extraction_method

    # Create one placeholder Chunk per page (real chunking in Phase 6)
    chunk = Chunk(
        page_id=page.id,
        chunk_type=ChunkType.TEXT,
        text=final_result.text,
        reading_order=0,
        review_status=ChunkReviewStatus.PENDING,
    )
    db.add(chunk)

    # Step J: Set status to awaiting_feedback, round 1
    page.status = PageStatus.AWAITING_FEEDBACK
    page.review_round = 1

    logger.debug(
        "Page %d processed (method=%s, score=%.2f, status=%s).",
        page.page_number, extraction_method.value, quality_score, page.status.value,
    )
def process_uploaded_pdf(
    db: Session,
    document: Document,
    pdf_path: str | Path,
) -> None:
    """Run the full per-page ingestion pipeline for a newly uploaded PDF.

    Called by POST /documents after file validation and disk save.  Sets
    document status to processing, determines page count, creates Page rows,
    processes each page via _process_single_page, then sets document status
    to awaiting_feedback.

    All writes are in a single transaction (NFR-12 / NFR-13).

    Args:
        db: SQLAlchemy session (caller commits after return).
        document: The Document row to process.
        pdf_path: Path to the saved PDF file on disk.
    """
    document.status = DocumentStatus.PROCESSING
    db.flush()

    # Deferred import avoids circular dependency
    from app.utils.pdf_utils import get_pdf_page_count

    page_count = get_pdf_page_count(pdf_path)
    document.page_count = page_count
    db.flush()

    logger.info(
        "Processing document %d (user=%d, filename='%s', pages=%d).",
        document.id, document.user_id, document.filename, page_count,
    )

    pages: list[Page] = []
    for page_num in range(1, page_count + 1):
        page = Page(
            document_id=document.id,
            page_number=page_num,
            status=PageStatus.INITIAL_PROCESSING,
            review_round=1,
        )
        db.add(page)
        pages.append(page)
    db.flush()

    for page in pages:
        _process_single_page(db, page, pdf_path)

    document.status = DocumentStatus.AWAITING_FEEDBACK
    logger.info("Document %d fully processed - status=%s.", document.id, document.status.value)


def reprocess_document(document_id: int) -> None:
    """Re-run ingestion on a document (FR-37 guard - not implemented).

    OD-8 default: re-upload is a brand-new Document row.  No automatic
    replacement or versioning.

    Raises:
        NotImplementedError: Always.
    """
    raise NotImplementedError(
        "reprocess_document() is not implemented per OD-8 default. "
        "Re-upload is treated as a brand-new Document row."
    )