"""Native Extractor placeholder.

Implements the "Native Extractor" component (SDD §4): extracts raw text,
tables, and images with captions from a page using native PDF parsing
(PyMuPDF).  Real implementation is added in Phase 3 — no business logic yet.
"""

# TODO(Phase 3): implement extract_page_native(pdf_path, page_number) -> PageContent