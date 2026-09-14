"""OCR Extractor — STUB implementation for Phase 2.

Implements the "OCR Extractor" component (SDD §4): extracts text, tables,
and images with captions from a page using OCR (tesseract), for pages that
fail the quality gate.

.. admonition:: Phase-2 STUB

    This is a **stub** that returns fixed placeholder content.  The real OCR
    logic (rasterizing the page with :mod:`app.services.page_rasterizer` then
    running Tesseract / cloud OCR) is implemented in **Phase 3**.

    The ``ExtractionResult`` dataclass and function signature are identical
    to :mod:`app.services.native_extractor` and are real — Phase 3 only
    replaces the function body.

.. warning::

    Do **not** confuse this with the native extractor.  ``extract_ocr`` is
    called only when ``score_quality()`` returns a value below
    ``settings.QUALITY_SCORE_THRESHOLD``.
"""

from pathlib import Path

from app.services.native_extractor import ExtractionResult


# STUB — replaced with real logic in Phase 3
def extract_ocr(pdf_path: str | Path, page_number: int) -> ExtractionResult:
    """Extract content from a PDF page using OCR.

    .. admonition:: Phase-2 STUB

        Returns a fixed placeholder.  Phase 3 will replace the body with
        real OCR logic (rasterize page → run Tesseract → extract text/tables).

    Args:
        pdf_path: Path to the PDF file on disk.
        page_number: 1-based page number to extract.

    Returns:
        An ``ExtractionResult`` with a placeholder text indicating the page
        number and the fact that OCR was used.  ``tables`` and ``images`` are
        empty lists in this stub.
    """
    # STUB — Phase 3 replaces everything below this line
    return ExtractionResult(
        text=f"[STUB Phase 2] OCR extraction placeholder for page {page_number} "
             f"of '{Path(pdf_path).name}'.  Real OCR arrives in Phase 3.",
    )