"""Quality Scorer — STUB implementation for Phase 2.

Implements the "Quality Scorer" component (SDD §4): computes a quality score
for a page's native extraction to decide whether OCR is needed.  The score
threshold is configurable via ``settings.QUALITY_SCORE_THRESHOLD`` (NFR-25).

.. admonition:: Phase-2 STUB

    This is a **stub** that always returns ``1.0`` (i.e. "perfect quality"),
    meaning the OCR fallback path is never triggered in Phase 2.  The real
    scoring logic (analysing extraction completeness, structure, density, etc.)
    is implemented in **Phase 3**.

    However, the **calling code** in ``ingestion_orchestrator.py`` DOES check
    ``if score < threshold:`` and calls ``extract_ocr`` — that code path
    genuinely exists and is tested.  Phase 3 simply swaps the stub scorer for
    a real one, and the OCR branch activates automatically.
"""

from pathlib import Path

from app.schemas.extraction_result import ExtractionResult

# Empirically-reasonable maximum character density (chars per point²).
# A typical text page (A4 ≈ 595×842 pts ≈ 500 000 pt²) with ~4000 characters
# yields ≈0.008 chars/pt².  We treat >=0.01 as "dense".
_CHAR_DENSITY_CEILING = 0.01

# Unicode category codes we consider "printable".
_PRINTABLE_CATEGORIES = frozenset({
    "Lu", "Ll", "Lt", "Lm", "Lo",  # Letters
    "Nd", "Nl", "No",              # Numbers
    "Pd", "Ps", "Pe", "Pi", "Pf",  # Punctuation
    "Po",                           # Other punctuation
    "Sm", "Sc", "Sk", "So",        # Symbols
    "Zs",                           # Space separator
})


def score_quality(
    extraction_result: ExtractionResult,
    page_rect: tuple[float, float, float, float],
) -> float:
    """Compute a composite quality score for a page's native extraction.

    The score is a float in ``[0.0, 1.0]`` — higher means better quality.
    Pages scoring below ``settings.QUALITY_SCORE_THRESHOLD`` fall through to
    OCR extraction (FR-10).

    [WORKING DEFAULT — OD-3]: Composite of character density (60%) and
    non-garbled ratio (40%).

    [WORKING DEFAULT — OD-13]: One score per page, not per block.

    Args:
        extraction_result: The content extracted by ``extract_native()``.
        page_rect: The PDF page's bounding rectangle
            ``(x0, y0, x1, y1)`` in points.

    Returns:
        A float in ``[0.0, 1.0]`` where higher indicates better quality.
    """
    # ── 1. Character density ─────────────────────────────────────────
    total_text = " ".join(tb.text for tb in extraction_result.text_blocks)
    total_chars = len(total_text)

    pw = page_rect[2] - page_rect[0]
    ph = page_rect[3] - page_rect[1]
    page_area = pw * ph
    if page_area <= 0:
        page_area = 1.0  # Prevent division by zero

    char_density = total_chars / page_area
    char_density_norm = min(char_density / _CHAR_DENSITY_CEILING, 1.0)

    # ── 2. Garbled-character ratio ──────────────────────────────────
    if total_chars == 0:
        garbled_score = 0.0  # Empty page → poor quality → triggers OCR
    else:
        printable_count = _count_printable_chars(total_text)
        garbled_ratio = 1.0 - (printable_count / total_chars)
        garbled_score = 1.0 - garbled_ratio  # Invert: higher = less garbled

    # ── 3. Composite ────────────────────────────────────────────────
    final_score = 0.6 * char_density_norm + 0.4 * garbled_score
    return max(0.0, min(1.0, final_score))


def _count_printable_chars(text: str) -> int:
    """Count characters that are alphanumeric or common punctuation."""
    import unicodedata

    count = 0
    for ch in text:
        try:
            cat = unicodedata.category(ch)
        except ValueError:
            cat = "Cn"
        if cat in _PRINTABLE_CATEGORIES:
            count += 1
        elif ch in (" ", "\t", "\n", "\r", "\xa0"):
            count += 1
    return count