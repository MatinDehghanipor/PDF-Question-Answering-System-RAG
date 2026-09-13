"""OCR Extractor placeholder.

Implements the "OCR Extractor" component (SDD §4): extracts text, tables,
and images with captions from a page using OCR (tesseract), for pages that
fail the quality gate.  Real implementation is added in Phase 3 — no business
logic yet.
"""

# TODO(Phase 3): implement extract_page_ocr(pdf_path, page_number) -> PageContent