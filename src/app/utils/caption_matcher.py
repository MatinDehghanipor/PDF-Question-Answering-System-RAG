"""Caption-matching heuristic for extracted images — [WORKING DEFAULT — OD-4].

Implements a LOCAL captioning approach for Phase 3 (native + OCR paths):
extract each image's immediately adjacent text block (if any, using proximity
to a "Figure X" / "Table X" style caption line) as the caption when present;
if no nearby caption text is found, fall back to a documented placeholder.

Explicitly does NOT call an LLM for captioning in this phase — that keeps
Phase 3 free of any LLM dependency, consistent with "Initial Processing
(cheapest, tried first)" from SDD §2.1.  LLM Review (Phase 5) DOES use a
vision LLM and will naturally produce higher-quality captions for pages that
reach that fallback, which is an intentional part of the cost ladder in SDD §2.1.
"""

import re
from typing import Optional

from app.schemas.extraction_result import TextBlock

# Regex to detect "Figure X" / "Table X" / "Fig. X" / "Table. X" style captions.
# Matches at the start of the text (after optional whitespace) so we don't
# accidentally grab a sentence that merely references a figure mid-text.
_CAPTION_PATTERN = re.compile(r"^\s*(fig(?:ure)?|table)\s*\.?\s*\d+", re.IGNORECASE)


def find_caption_for_image(
    image_bbox: tuple[float, float, float, float],
    text_blocks: list[TextBlock],
    page_number: int,
    image_index: int,
) -> str:
    """Attempt to locate a caption for an image using proximity to text blocks.

    Strategy (OD-4 default):
    1. Scan text blocks whose horizontal range overlaps the image's bounding
       box (so we don't pick up unrelated text from other columns).
    2. Look for the **closest** text block **below** the image first — typical
       caption placement (below a figure/table).
    3. If nothing matched below, check the closest block **above** the image.
    4. If a candidate text block matches the ``Figure X`` / ``Table X``
       pattern, return that text as the caption.
    5. If no caption-like text is found in proximity, return the documented
       placeholder string.

    Args:
        image_bbox: The image's bounding box ***(x0, y0, x1, y1)*** in PDF
            points.
        text_blocks: All :class:`TextBlock` objects from the same page, in
            reading order.
        page_number: 1-based page number (used in the placeholder).
        image_index: Zero-based image index on this page (used in the
            placeholder).

    Returns:
        A caption string (matched text or the OD-4 placeholder).
    """
    image_x0, image_y0, image_x1, image_y1 = image_bbox

    # Separate overlapping candidates by direction (below / above)
    candidates_below: list[tuple[float, TextBlock]] = []
    candidates_above: list[tuple[float, TextBlock]] = []

    for tb in text_blocks:
        tx0, ty0, tx1, ty1 = tb.bbox
        # Must have horizontal overlap with the image
        if tx1 < image_x0 or tx0 > image_x1:
            continue

        # Below the image: block's top edge is at or below image's bottom edge
        if ty0 >= image_y1:
            distance = ty0 - image_y1
            candidates_below.append((distance, tb))
        # Above the image: block's bottom edge is at or above image's top edge
        elif ty1 <= image_y0:
            distance = image_y0 - ty1
            candidates_above.append((distance, tb))

    # Check closest block below, then above
    for candidates in [candidates_below, candidates_above]:
        candidates.sort(key=lambda pair: pair[0])  # closest first
        if candidates:
            _, closest_block = candidates[0]
            text = closest_block.text.strip()
            if _CAPTION_PATTERN.match(text):
                return text
            # Sometimes there is a blank line / whitespace-only block between
            # the image and the caption; check the next-closest block too.
            if len(candidates) > 1:
                _, next_block = candidates[1]
                next_text = next_block.text.strip()
                if _CAPTION_PATTERN.match(next_text):
                    return next_text

    # No caption-like text found in proximity — return placeholder
    return (
        f"Image on page {page_number}, position {image_index} "
        f"(no caption text detected)"
    )