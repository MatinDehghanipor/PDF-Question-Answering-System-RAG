"""Ingestion Orchestrator — per-page state machine (Phase 3).

Implements the core orchestration logic of the "Document and Page Registry"
component (SDD §4): drives each page of an uploaded PDF through the initial
extraction pipeline and lands it in the "Awaiting Feedback, Round 1" state
with real content chunks ready for human review.

Pipeline flow (SDD §5.1):
    A. Upload -> B. Validate -> D. Split -> E. For each page:
        F. ``extract_native()`` — real native extraction (Phase 3)
        G. ``score_quality()`` — real quality scoring (Phase 3)
        H. If score < threshold -> I. ``extract_ocr()`` — real OCR (Phase 3)
        J. Create typed Chunks per extracted block
        K. Set status = ``awaiting_feedback``, round 1

Per-page error handling realises NFR-14: a failure on one page never aborts
the entire document's ingestion.
"""

import logging
from pathlib import Path

import fitz  # PyMuPDF — used here to obtain page rect for quality scoring
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
from app.schemas.extraction_result import ExtractionResult
from app.services.native_extractor import extract_native
from app.services.ocr_extractor import extract_ocr
from app.services.quality_scorer import score_quality

logger = logging.getLogger(__name__)


def _process_single_page(
    db: Session,
    page: Page,
    pdf_path: str | Path,
) -> None:
    """Run the per-page extraction pipeline (SDD 5.1 steps F->G->H->I->J->K).

    1. Calls real native extractor — F
    2. Calls real quality scorer with page rect — G
    3. If quality below threshold, calls real OCR extractor — H->I
    4. Creates typed Chunks per extracted text/table/image block — J
    5. Sets page status to awaiting_feedback, round 1 — K

    Error handling (NFR-14):
    - If native extraction raises, treat quality score as 0 → OCR fallback.
    - If OCR extraction fails, set extraction_method to ``ocr_failed``.
    - Per-block table/image failures are caught inside each extractor.
    - A single page failure never aborts the document loop (caller's
      responsibility — ``process_uploaded_pdf`` loops over pages).

    Args:
        db: SQLAlchemy session (transaction managed by caller).
        page: The Page row to process.
        pdf_path: Path to the PDF file on disk.
    """
    page.status = PageStatus.INITIAL_PROCESSING
    db.flush()

    # ── Step F: Native extraction ───────────────────────────────────
    try:
        native_result: ExtractionResult = extract_native(pdf_path, page.page_number)
        native_ok = True
    except Exception as exc:
        logger.warning(
            "Native extraction failed for page %d of '%s': %s — falling through to OCR.",
            page.page_number, pdf_path, exc,
        )
        native_result = ExtractionResult()
        native_ok = False

    # ── Get page rect for quality scoring ───────────────────────────
    page_rect = _get_page_rect(pdf_path, page.page_number)

    # ── Step G: Quality scoring ─────────────────────────────────────
    quality_score: float = score_quality(native_result, page_rect)
    page.quality_score = quality_score

    # ── Steps H->I: OCR fallback ────────────────────────────────────
    if not native_ok or quality_score < settings.QUALITY_SCORE_THRESHOLD:
        if native_ok:
            logger.info(
                "Page %d quality score %.2f below threshold %.2f — OCR fallback.",
                page.page_number, quality_score, settings.QUALITY_SCORE_THRESHOLD,
            )
        try:
            ocr_result: ExtractionResult = extract_ocr(pdf_path, page.page_number)
            extraction_method = ExtractionMethod.OCR
            final_result = ocr_result
        except Exception as exc:
            logger.error(
                "OCR extraction also failed for page %d of '%s': %s — "
                "marking as ocr_failed.",
                page.page_number, pdf_path, exc,
            )
            extraction_method = ExtractionMethod.OCR_FAILED
            final_result = ExtractionResult()  # Empty — no content for this page
    else:
        extraction_method = ExtractionMethod.NATIVE
        final_result = native_result

    page.extraction_method = extraction_method

    # ── Step J: Create typed Chunks per extracted block ─────────────
    _create_chunks_for_page(db, page.id, final_result)

    # ── Step K: Set status to awaiting_feedback, round 1 ────────────
    page.status = PageStatus.AWAITING_FEEDBACK
    page.review_round = 1

    logger.debug(
        "Page %d processed (method=%s, score=%.2f, chunks=%d, status=%s).",
        page.page_number,
        extraction_method.value if extraction_method else "none",
        quality_score,
        len(final_result.text_blocks) + len(final_result.tables) + len(final_result.images),
        page.status.value,
    )


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _get_page_rect(
    pdf_path: str | Path,
    page_number: int,
) -> tuple[float, float, float, float]:
    """Open the PDF and return the page's bounding rectangle.

    Returns ``(x0, y0, x1, y1)`` in points.  Falls back to a sensible
    default (A4 portrait) if the PDF cannot be opened, so a bad page never
    blocks the pipeline (NFR-14).
    """
    try:
        doc = fitz.open(pdf_path)
        idx = page_number - 1
        if 0 <= idx < doc.page_count:
            r = doc[idx].rect
            doc.close()
            return (r.x0, r.y0, r.x1, r.y1)
        doc.close()
    except Exception:
        logger.debug("Could not get page rect for page %d; using A4 default.", page_number)
    # A4 portrait fallback: 595 × 842 points
    return (0.0, 0.0, 595.0, 842.0)


def _create_chunks_for_page(
    db: Session,
    page_id: int,
    result: ExtractionResult,
) -> None:
    """Create one :class:`Chunk` per extracted block for *page_id*.

    Sets ``reading_order`` sequentially across text → table → image blocks
    so the original page layout can be reconstructed during review (Phase 4)
    and prompt assembly (Phase 7).
    """
    reading_order = 0

    for tb in result.text_blocks:
        chunk = Chunk(
            page_id=page_id,
            chunk_type=ChunkType.TEXT,
            text=tb.text,
            reading_order=reading_order,
            review_status=ChunkReviewStatus.PENDING,
        )
        db.add(chunk)
        reading_order += 1

    for tab in result.tables:
        chunk = Chunk(
            page_id=page_id,
            chunk_type=ChunkType.TABLE,
            table_markdown=tab.markdown,
            reading_order=reading_order,
            review_status=ChunkReviewStatus.PENDING,
        )
        db.add(chunk)
        reading_order += 1

    for img in result.images:
        chunk = Chunk(
            page_id=page_id,
            chunk_type=ChunkType.IMAGE,
            image_caption=img.caption,
            image_path=img.path,
            reading_order=reading_order,
            review_status=ChunkReviewStatus.PENDING,
        )
        db.add(chunk)
        reading_order += 1

    if reading_order == 0:
        logger.warning("Page %d produced zero extractable blocks — creating empty placeholder.", page_id)
        chunk = Chunk(
            page_id=page_id,
            chunk_type=ChunkType.TEXT,
            text="[No extractable content on this page]",
            reading_order=0,
            review_status=ChunkReviewStatus.PENDING,
        )
        db.add(chunk)

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
