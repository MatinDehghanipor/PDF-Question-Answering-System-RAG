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

from app.services.native_extractor import ExtractionResult


# STUB — replaced with real logic in Phase 3
def score_quality(extraction_result: ExtractionResult) -> float:
    """Compute a quality score for a page's native extraction.

    .. admonition:: Phase-2 STUB

        Returns ``1.0`` (always above ``QUALITY_SCORE_THRESHOLD``) so the OCR
        branch is never triggered during Phase 2.  Phase 3 replaces the body
        with real heuristic or ML-based scoring.

    Args:
        extraction_result: The content extracted by ``extract_native``.

    Returns:
        A float in ``[0.0, 1.0]`` where higher is better quality.
        Always ``1.0`` in this stub.
    """
    # STUB — Phase 3 replaces everything below this line
    return 1.0