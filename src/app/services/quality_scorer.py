"""Quality Scorer placeholder.

Implements the "Quality Scorer" component (SDD §4): computes a quality score
for a page's native extraction to decide whether OCR is needed.  The score
threshold is configurable via ``settings.QUALITY_SCORE_THRESHOLD`` (NFR-25).
Real implementation is added in Phase 3 — no business logic yet.
"""

# TODO(Phase 3): implement score_page(native_content, threshold) -> float