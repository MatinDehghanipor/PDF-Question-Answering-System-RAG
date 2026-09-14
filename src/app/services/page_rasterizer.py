"""Page Rasterizer — render a PDF page as a PNG image (Phase 5).

Implements the "Page Rasterizer" component (SDD §4): renders a single PDF
page to a high-quality PNG image byte string, used as input to the vision
LLM during LLM Review (FR-14).

Uses PyMuPDF ``page.get_pixmap(dpi=200)`` then ``pixmap.tobytes("png")``.
200 DPI balances image size/token cost against legibility for the vision LLM.
"""

import logging
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)


def render_page_to_png(
    pdf_path: str | Path,
    page_number: int,
    dpi: int = 200,
) -> bytes:
    """Render a PDF page as a PNG image.

    Args:
        pdf_path: Path to the PDF file.
        page_number: 1-based page number.
        dpi: Rendering resolution (default 200).

    Returns:
        PNG image bytes.

    Raises:
        RuntimeError: If the PDF cannot be opened or page is out of range.
    """
    try:
        doc: fitz.Document = fitz.open(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Cannot open PDF '{pdf_path}': {exc}") from exc

    idx = page_number - 1
    if idx < 0 or idx >= doc.page_count:
        doc.close()
        raise RuntimeError(f"Page {page_number} out of range (PDF has {doc.page_count} pages).")

    try:
        pix = doc[idx].get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
    finally:
        doc.close()

    return png_bytes