"""OCR Extractor — real implementation (Phase 3).

Implements the "OCR Extractor" component (SDD §4): extracts text, tables,
and images with captions from a page using OCR (Tesseract), for pages that
fail the quality gate.

Pipeline:
1. Render the PDF page to a high-DPI image (300 DPI) via PyMuPDF.
2. Run Tesseract OCR on the rendered image for text.
3. Attempt Camelot table extraction on the original PDF (same as native path).
4. Extract embedded images from the original PDF with caption proximity.

The output shape (:class:`~app.schemas.extraction_result.ExtractionResult`) is
IDENTICAL to that produced by the native extractor (SDD §2.2) so downstream
code is extractor-agnostic.
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
# Tesseract import — may fail at import time if the system binary
# (tesseract-ocr) is not installed (NFR-14 catch).
# ──────────────────────────────────────────────────────────────────────
try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except Exception as exc:
    pytesseract = None  # type: ignore[assignment]
    _TESSERACT_AVAILABLE = False
    logger.warning(
        "pytesseract import failed (%s); OCR fallback will be unavailable. "
        "Install Tesseract system binary + pip package.", exc,
    )

# Reuse Camelot detection from the native path
try:
    import camelot  # noqa: F401
    _CAMELOT_AVAILABLE = True
except Exception as exc:
    camelot = None  # type: ignore[assignment]
    _CAMELOT_AVAILABLE = False
    logger.warning(
        "camelot-py import failed (%s); table extraction in OCR path disabled.", exc,
    )

# ──────────────────────────────────────────────────────────────────────
# FR-37 reprocessing guard
# ──────────────────────────────────────────────────────────────────────
_processed_ocr: set[tuple[str, int]] = set()


def _check_reprocess_guard(pdf_path: str | Path, page_number: int) -> None:
    """Warn if this (pdf_path, page_number) was already OCR-extracted (FR-37)."""
    key = (str(pdf_path), page_number)
    if key in _processed_ocr:
        logger.warning(
            "FR-37 guard: extract_ocr called again for '%s' page %d.",
            pdf_path, page_number,
        )
    _processed_ocr.add(key)


def extract_ocr(pdf_path: str | Path, page_number: int) -> ExtractionResult:
    """Extract content from a PDF page using OCR (FR-10 / FR-8 via OCR).

    Called when ``score_quality()`` returns a value below
    ``settings.QUALITY_SCORE_THRESHOLD``.  Produces the same shape of result
    as :func:`~app.services.native_extractor.extract_native`.

    Args:
        pdf_path: Path to the PDF file on disk.
        page_number: **1-based** page number.

    Returns:
        An :class:`ExtractionResult` with OCR-extracted text blocks, any
        detectable tables (Markdown), and captioned images.

    Raises:
        RuntimeError: If the PDF cannot be opened.
        pytesseract.TesseractNotFoundError: (re-raised) if the Tesseract
            binary is not available — the caller should catch this and mark
            the page as ``ocr_failed``.
    """
    _check_reprocess_guard(pdf_path, page_number)
    try:
        doc: fitz.Document = fitz.open(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Cannot open PDF '{pdf_path}': {exc}") from exc

    fitz_index = page_number - 1
    if fitz_index < 0 or fitz_index >= doc.page_count:
        doc.close()
        raise RuntimeError(
            f"Page {page_number} out of range (PDF has {doc.page_count} pages)."
        )
    page: fitz.Page = doc[fitz_index]

    try:
        # 1. Render page to high-DPI image for OCR
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")

        # 2. OCR text
        text_blocks = _ocr_text_blocks(img_bytes)

        # 3. Tables via Camelot on original PDF
        tables = _ocr_extract_tables(doc, pdf_path, page_number)

        # 4. Images from original PDF
        images = _extract_images(doc, page, page_number, text_blocks)
    finally:
        doc.close()

    return ExtractionResult(text_blocks=text_blocks, tables=tables, images=images)
# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _ocr_text_blocks(png_bytes: bytes) -> list[TextBlock]:
    """Run Tesseract OCR on a page image and return text blocks.

    .. note::
        Tesseract defaults to English-only OCR.  If the document language
        is known (e.g., Persian), install the matching language pack and
        pass ``lang="fas+eng"`` to ``image_to_string()``.

    Returns:
        A list with a single :class:`TextBlock` containing the full OCR
        output (no bounding-box information from Tesseract in this version).
    """
    if not _TESSERACT_AVAILABLE:
        raise RuntimeError(
            "pytesseract is not available — cannot perform OCR. "
            "Install the system binary (tesseract-ocr) and the pip package."
        )
    text = pytesseract.image_to_string(png_bytes)  # type: ignore[arg-type]
    return [TextBlock(text=text.strip(), bbox=(0.0, 0.0, 0.0, 0.0))]


def _ocr_extract_tables(
    doc: fitz.Document,
    pdf_path: str | Path,
    page_number: int,
) -> list[TableBlock]:
    """Attempt table extraction on an OCR / scanned PDF via Camelot.

    .. admonition:: Limitation
        Camelot's ``stream`` flavour can work on scanned PDFs, but with
        **lower reliability** than on digital-native PDFs.  This is
        documented rather than silently hidden.
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
                logger.debug("Camelot '%s' failed on OCR page %d: %s", flavor, page_number, exc)
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
        logger.warning("OCR table extraction failed for page %d: %s", page_number, exc)
    return tables


def _extract_images(
    doc: fitz.Document,
    page: fitz.Page,
    page_number: int,
    text_blocks: list[TextBlock],
) -> list[ImageBlock]:
    """Extract embedded images from the original PDF (same as native path)."""
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
            logger.warning("Failed to extract image %d on OCR page %d: %s", img_idx, page_number, exc)
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