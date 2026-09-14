"""Native Extractor — STUB implementation for Phase 2.

Implements the "Native Extractor" component (SDD §4): extracts raw text,
tables, and images with captions from a page using native PDF parsing
(PyMuPDF).

.. admonition:: Phase-2 STUB

    This is a **stub** that returns fixed placeholder content.  The real
    extraction logic (using PyMuPDF to walk page content streams, detect
    tables, and extract images) is implemented in **Phase 3**.

    The ``ExtractionResult`` dataclass and function signature are real and
    will not change — Phase 3 only replaces the function body.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractionResult:
    """Structured content extracted from a single page.

    Attributes:
        text: The plain text content of the page.
        tables: Markdown-serialized table representations.
        images: Filesystem paths to extracted images from the page.
        image_captions: Captions for each extracted image (same order as
            ``images``).
    """

    text: str = ""
    tables: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    image_captions: list[str] = field(default_factory=list)


# STUB — replaced with real logic in Phase 3
def extract_native(pdf_path: str | Path, page_number: int) -> ExtractionResult:
    """Extract content from a PDF page using native PDF parsing.

    .. admonition:: Phase-2 STUB

        Returns a fixed placeholder.  Phase 3 will replace the body with
        real ``fitz`` content-stream walking, table detection, and image
        extraction logic.

    Args:
        pdf_path: Path to the PDF file on disk.
        page_number: 1-based page number to extract.

    Returns:
        An ``ExtractionResult`` with a placeholder text indicating the page
        number.  ``tables`` and ``images`` are empty lists in this stub.
    """
    # STUB — Phase 3 replaces everything below this line
    return ExtractionResult(
        text=f"[STUB Phase 2] Native extraction placeholder for page {page_number} "
             f"of '{Path(pdf_path).name}'.  Real extraction arrives in Phase 3.",
    )