"""Native Extractor — real implementation (Phase 3).

Implements the "Native Extractor" component (SDD §4): extracts text, tables,
and images with captions from a page using native PDF parsing (PyMuPDF).

Uses:
- ``fitz.Page.get_text("blocks")`` — retrieves text blocks with bounding boxes
  for reading-order sorting and caption-proximity matching.
- ``camelot.read_pdf()`` — detects and serialises tables to Markdown (FR-18),
  trying ``lattice`` flavour first, falling back to ``stream``.
- ``fitz.Page.get_images()`` + ``fitz.Document.extract_image()`` — retrieves
  embedded images and saves them to disk (FR-19).

The output shape (:class:`~app.schemas.extraction_result.ExtractionResult`) is
identical to that produced by the OCR extractor and the future LLM Review
extractor, so downstream code is extractor-agnostic (SDD §2.2).

Per-page error wrapping realises NFR-14: a failure on one page never aborts
the entire document's ingestion.
"""

import logging
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.extraction_result import (
    ExtractionResult,
    ImageBlock,
    TableBlock,
    TextBlock,
)
from app.utils.caption_matcher import find_caption_for_image

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Camelot import with graceful fallback (NFR-14 at import level).
# ──────────────────────────────────────────────────────────────────────
try:
    import camelot  # noqa: F401
    _CAMELOT_AVAILABLE = True
except Exception as exc:
    camelot = None  # type: ignore[assignment]
    _CAMELOT_AVAILABLE = False
    logger.warning(
        "camelot-py import failed (%s); table extraction disabled. "
        "Ensure Ghostscript is installed and on PATH.", exc,
    )

# ──────────────────────────────────────────────────────────────────────
# FR-37 reprocessing guard
# ──────────────────────────────────────────────────────────────────────
_processed_native: set[tuple[str, int]] = set()


def _check_reprocess_guard(pdf_path: str | Path, page_number: int) -> None:
    """Warn if this (pdf_path, page_number) was already extracted (FR-37).

    This is an in-memory guard — it resets on process restart.  In production
    the database row status is the authoritative gatekeeper.
    """
    key = (str(pdf_path), page_number)
    if key in _processed_native:
        logger.warning(
            "FR-37 guard: extract_native called again for '%s' page %d.",
            pdf_path, page_number,
        )
    _processed_native.add(key)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def extract_native(
    pdf_path: str | Path,
    page_number: int,
) -> ExtractionResult:
    """Extract text, tables, and captioned images from a PDF page (FR-8).

    This is the **fast path** — native parsing only, no OCR or LLM call.
    Pages that score below ``settings.QUALITY_SCORE_THRESHOLD`` will be
    re-extracted via :func:`app.services.ocr_extractor.extract_ocr`.

    Args:
        pdf_path: Path to the PDF file on disk.
        page_number: **1-based** page number (internally converted to
            PyMuPDF's 0-based index).

    Returns:
        An :class:`ExtractionResult` with text blocks, Markdown tables,
        and captioned images.  Any of the three lists may be empty.

    Raises:
        RuntimeError: If the PDF cannot be opened or the page does not
            exist.  The caller should catch this and treat quality as 0,
            triggering OCR fallback.
    """
    _check_reprocess_guard(pdf_path, page_number)
    try:
        doc: fitz.Document = fitz.open(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Cannot open PDF '{pdf_path}': {exc}") from exc

    fitz_page_index = page_number - 1
    if fitz_page_index < 0 or fitz_page_index >= doc.page_count:
        page_count = doc.page_count
        doc.close()
        raise RuntimeError(
            f"Page {page_number} out of range (PDF has {page_count} pages)."
        )
    page: fitz.Page = doc[fitz_page_index]

    try:
        text_blocks = _extract_text_blocks(page)
        tables = _extract_tables(doc, pdf_path, page_number)
        images = _extract_images(doc, page, page_number, text_blocks)
    finally:
        doc.close()

    return ExtractionResult(
        text_blocks=text_blocks,
        tables=tables,
        images=images,
    )


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _extract_text_blocks(page: fitz.Page) -> list[TextBlock]:
    """Extract text blocks in approximate reading order.

    PyMuPDF's ``get_text("blocks")`` returns tuples
    ``(x0, y0, x1, y1, text, block_type, block_no)``.
    Sort by ``(y0, x0)`` for top-to-bottom, left-to-right order.

    .. note::
        Multi-column PDFs may need manual re-ordering during review (Phase 4).
    """
    raw = page.get_text("blocks")
    blocks: list[TextBlock] = []
    for b in raw:
        x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
        text = (b[4] or "").strip()
        if not text:
            continue
        blocks.append(TextBlock(text=text, bbox=(x0, y0, x1, y1)))
    blocks.sort(key=lambda tb: (tb.bbox[1], tb.bbox[0]))
    return blocks


def _extract_tables(
    doc: fitz.Document,
    pdf_path: str | Path,
    page_number: int,
) -> list[TableBlock]:
    """Detect tables via Camelot (FR-18).  Tries lattice then stream.

    Returns:
        List of :class:`TableBlock`.  Empty on any failure (NFR-14).
    """
    if not _CAMELOT_AVAILABLE:
        return []

    tables: list[TableBlock] = []
    try:
        for flavor in ("lattice", "stream"):
            try:
                detected = camelot.read_pdf(
                    str(pdf_path), pages=str(page_number), flavor=flavor,
                )
            except Exception as exc:
                logger.debug("Camelot '%s' failed on page %d: %s", flavor, page_number, exc)
                continue

            if detected.n > 0:
                for table in detected:
                    df = table.df
                    if df.empty or df.iloc[:, 0].isna().all():
                        continue
                    markdown = df.to_markdown(index=False)
                    bbox = getattr(table, "_bbox", (0.0, 0.0, 0.0, 0.0))
                    if bbox and len(bbox) == 4:
                        bbox = tuple(float(v) for v in bbox)
                    tables.append(TableBlock(markdown=markdown, bbox=bbox))
                if flavor == "lattice" and tables:
                    break
    except Exception as exc:
        logger.warning("Table extraction failed for page %d: %s", page_number, exc)
    return tables


def _extract_images(
    doc: fitz.Document,
    page: fitz.Page,
    page_number: int,
    text_blocks: list[TextBlock],
) -> list[ImageBlock]:
    """Extract embedded images, save them, and attach captions (FR-19).

    Images are saved to a ``_images/page_{n}/`` subdirectory next to the PDF.
    Each image gets a caption via the OD-4 proximity heuristic.
    """
    images: list[ImageBlock] = []
    pdf_path = Path(doc.name) if doc.name else Path(".")
    images_root = pdf_path.parent / "_images" / f"page_{page_number}"
    try:
        images_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        images_root = Path(".")

    for img_idx, img_ref in enumerate(page.get_images(full=True)):
        try:
            xref = img_ref[0]
            base = doc.extract_image(xref)
            ext = base["ext"]
            filename = f"page_{page_number}_img_{img_idx}.{ext}"
            img_path = images_root / filename
            with open(img_path, "wb") as f:
                f.write(base["image"])

            bbox = _get_image_bbox(page, img_ref, xref)
            caption = find_caption_for_image(bbox, text_blocks, page_number, img_idx)
            images.append(ImageBlock(caption=caption, path=str(img_path.resolve()), bbox=bbox))
        except Exception as exc:
            logger.warning("Failed to extract image %d on page %d: %s", img_idx, page_number, exc)
            continue
    return images


def _get_image_bbox(
    page: fitz.Page,
    img_ref: list,
    xref: int,
) -> tuple[float, float, float, float]:
    """Return the bounding box of an image on *page*."""
    try:
        bbox = page.get_image_bbox(xref)
        if bbox:
            return (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    except Exception:
        pass
    return (0.0, 0.0, 0.0, 0.0)