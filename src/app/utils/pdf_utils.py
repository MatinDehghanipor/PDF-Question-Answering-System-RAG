"""PDF file validation and page-count utilities for Phase 2.

This module provides two responsibilities that are needed as early as Phase 2
but do not belong to any of the SDD §4 "extractor" services:

1.  **File-type validation** (actual PDF magic bytes + extension check) for the
    upload gate (FR-5).
2.  **Page-count detection** so the orchestrator can create the correct number
    of ``Page`` rows before running the per-page pipeline.

``PyMuPDF`` (``fitz``) is used in **this file only** and only for
``doc.page_count`` — it is NOT used for text/table/image extraction.  That
boundary is intentional: real extraction is Phase 3's job.  If you need to
extract text or parse PDF internals, do it in ``services/native_extractor.py``
(where PyMuPDF will also be the tool, but with a different usage pattern).

.. admonition:: Phase-2 boundary note

    PyMuPDF is allowed in Phase 2 **only** for ``doc.page_count``.  If a later
    phase needs to change or remove this function, the extraction boundary
    comment above makes it safe to do so without worrying about hidden
    extraction logic.
"""

import logging
from pathlib import Path

import fitz  # PyMuPDF — used here ONLY for page_count (Phase-2 boundary)

from app.core.config import settings

logger = logging.getLogger(__name__)

# PDF magic bytes as defined by ISO 32000-1
PDF_MAGIC_BYTES = b"%PDF-"


class PdfValidationError(ValueError):
    """Raised when an uploaded file fails validation as a PDF."""


class PdfProcessingError(RuntimeError):
    """Raised when a valid PDF cannot be parsed or split."""


def validate_pdf_file(filename: str, file_bytes: bytes) -> None:
    """Validate that ``file_bytes`` is a genuine PDF (FR-5).

    Checks both the file extension and the PDF magic-byte header.  Either
    alone is insufficient: a ``.txt`` renamed to ``.pdf`` has the right
    extension but wrong content; a ``%PDF-`` prefix inside a non-PDF file
    (extremely rare) would pass the magic check but still fail PyMuPDF later.

    Args:
        filename: The original upload filename (used for extension check).
        file_bytes: The raw file content.

    Raises:
        PdfValidationError: If the file is not a valid PDF based on
            extension, magic bytes, or size limits.

    Note:
        This function intentionally does **not** open the file with PyMuPDF —
        that is deferred to ``get_pdf_page_count()`` so the two concerns
        (validation vs. parsing) stay separate.
    """
    # --- Extension check ---
    if not filename.lower().endswith(".pdf"):
        raise PdfValidationError(
            f"File '{filename}' does not have a '.pdf' extension."
        )

    # --- Magic-byte check ---
    if not file_bytes.startswith(PDF_MAGIC_BYTES):
        raise PdfValidationError(
            f"File '{filename}' is not a valid PDF (missing '%PDF-' header)."
        )

    # --- Size check ---
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise PdfValidationError(
            f"File '{filename}' exceeds the maximum upload size of "
            f"{settings.MAX_UPLOAD_SIZE_MB} MB "
            f"(file size: {len(file_bytes) / (1024 * 1024):.1f} MB)."
        )


def get_pdf_page_count(file_path: str | Path) -> int:
    """Return the number of pages in a PDF file (FR-6).

    Uses PyMuPDF (``fitz``) **only** to count pages.  No text, table, or
    image extraction is performed — that is Phase 3's responsibility in
    :mod:`app.services.native_extractor`.

    Args:
        file_path: Path to the saved PDF on disk.

    Returns:
        The total number of pages in the document.

    Raises:
        PdfProcessingError: If the PDF cannot be opened or is corrupted.

    .. admonition:: Phase-2 boundary

        This is the **only** use of ``fitz`` in Phase 2.  When real extraction
        arrives in Phase 3, ``native_extractor.py`` will also import ``fitz``,
        but for the different purpose of parsing page content.
    """
    try:
        doc = fitz.open(file_path)
        page_count = doc.page_count
        doc.close()
    except Exception as exc:
        raise PdfProcessingError(
            f"Cannot open PDF at '{file_path}': {exc}"
        ) from exc

    if page_count == 0:
        raise PdfProcessingError(
            f"PDF at '{file_path}' has zero pages — refusing to process."
        )

    return page_count


def ensure_storage_path(user_id: int, document_id: int) -> Path:
    """Return the full path where a user's document PDF is stored.

    The file is always stored under ``FILE_STORAGE_PATH/{user_id}/{document_id}.pdf``
    to avoid filename collisions between users and to satisfy NFR-22 (secure
    file handling tied to the user-specific directory).

    Args:
        user_id: The owning user's id.
        document_id: The document's database id.

    Returns:
        The absolute ``Path`` where the PDF should be saved.
    """
    storage_root = Path(settings.FILE_STORAGE_PATH)
    user_dir = storage_root / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / f"{document_id}.pdf"