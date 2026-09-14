"""LLM Service — real implementation (Phase 5).

Implements the "LLM Service" component (SDD §4): performs LLM Review via
vision LLM (OD-12: separate configurable model).  Exposes
``trigger_llm_review()`` replacing the Phase-4 stub.

[WORKING DEFAULT — OD-11]: Structured JSON prompt.
[WORKING DEFAULT — OD-12]: ``LLM_REVIEW_MODEL`` independent of ``LLM_ANSWER_MODEL``.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.enums import (
    ChunkReviewStatus,
    ChunkType,
    ExtractionMethod,
    PageStatus,
    TokenUsageContextType,
)
from app.models.page import Page
from app.schemas.extraction_result import ExtractionResult, ImageBlock, TableBlock, TextBlock
from app.services.page_rasterizer import render_page_to_png
from app.services.token_tracker import record_token_usage, estimate_tokens

logger = logging.getLogger(__name__)

# [WORKING DEFAULT — OD-11]: Structured-JSON prompt for LLM Review.
# {optional_note_block} is substituted with the user's review_note (OD-14).
LLM_REVIEW_PROMPT_TEMPLATE = """You are extracting structured content from a single scanned/rendered page image. Return ONLY valid JSON (no prose, no Markdown fences) matching this schema:
{
  "text_blocks": ["..."],
  "tables": ["<markdown table string>"],
  "images": [{"caption": "...", "bbox_description": "..."}]
}
Rules:
- Preserve reading order in the order you list text_blocks.
- Convert every table you see into a valid Markdown table string.
- For every distinct photo/figure/diagram on the page, add one entry to 'images' with your best-effort caption describing its content.
- Do not invent content that is not visibly present on the page.
{optional_note_block}"""


def trigger_llm_review(db: Session, page_id: int, note: str | None = None) -> None:
    """Run LLM Review for a Round-1 rejected page (FR-14–FR-16)."""
    page = db.get(Page, page_id)
    if page is None:
        raise ValueError(f"Page {page_id} not found.")
    if page.status != PageStatus.LLM_REVIEW:
        raise ValueError(f"Page {page_id} is '{page.status.value}', expected 'llm_review'.")

    doc = page.document
    pdf_path = Path(settings.FILE_STORAGE_PATH) / str(doc.user_id) / f"{doc.id}.pdf"

    try:
        image_bytes = render_page_to_png(pdf_path, page.page_number, dpi=200)
    except Exception as exc:
        page.extraction_method = ExtractionMethod.LLM_REVIEW_FAILED; db.flush()
        raise RuntimeError(f"Failed to render page {page_id}: {exc}") from exc

    note_block = f"Additional guidance from the user who rejected the previous extraction: {note}" if note else ""
    prompt = LLM_REVIEW_PROMPT_TEMPLATE.format(optional_note_block=note_block)

    try:
        result = call_vision_llm(image_bytes, prompt, settings.LLM_REVIEW_MODEL)
    except Exception as exc:
        page.extraction_method = ExtractionMethod.LLM_REVIEW_FAILED; db.flush()
        raise RuntimeError(f"Vision LLM call failed for page {page_id}: {exc}") from exc

    try:
        parsed = json.loads(result.text)
    except json.JSONDecodeError as exc:
        page.extraction_method = ExtractionMethod.LLM_REVIEW_FAILED; db.flush()
        logger.error("Malformed JSON for page %d: %s", page_id, result.text[:500])
        raise RuntimeError(f"Invalid JSON for page {page_id}: {exc}") from exc

    _replace_page_chunks(db, page, _parse_llm_response(parsed))

    pt = result.prompt_tokens
    ct = result.completion_tokens
    est = False
    if pt is None or ct is None:
        pt, ct = estimate_tokens(prompt), estimate_tokens(result.text); est = True
    record_token_usage(db=db, user_id=doc.user_id, context_type=TokenUsageContextType.LLM_REVIEW,
                       context_id=page.id, model_used=settings.LLM_REVIEW_MODEL,
                       prompt_tokens=pt, completion_tokens=ct, is_estimated=est)

    page.extraction_method = ExtractionMethod.LLM_VISION
    page.review_round = 2
    page.status = PageStatus.AWAITING_FEEDBACK
    page.updated_at = datetime.utcnow()
    db.flush()
# ══════════════════════════════════════════════════════════════════════
# Internal: call_vision_llm (provider-agnostic interface)
# ══════════════════════════════════════════════════════════════════════


class LLMCallResult:
    """Result from a vision LLM call."""
    def __init__(self, text: str, prompt_tokens: int | None = None, completion_tokens: int | None = None) -> None:
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


def call_vision_llm(image_bytes: bytes, prompt: str, model: str) -> LLMCallResult:
    """Send a page image and extraction prompt to a vision-capable LLM.

    Uses Google Generative AI SDK (gemini) as the default provider (SDD §3).
    The image is sent as a base64 data URI per Gemini's InlineData format.

    Args:
        image_bytes: PNG image bytes.
        prompt: Extraction prompt (OD-11 template).
        model: Model identifier (e.g. ``gemini-2.0-flash``).

    Returns:
        LLMCallResult with response text and token counts.

    Raises:
        RuntimeError: If the API call fails or API key is missing.
    """
    try:
        import google.genai as genai
    except ImportError:
        raise RuntimeError("google-generativeai SDK not installed. Install via: pip install google-generativeai")

    import os, base64
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")

    client = genai.Client(api_key=api_key)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_data_uri = f"data:image/png;base64,{b64}"

    try:
        response = client.models.generate_content(model=model, contents=[prompt, image_data_uri])
    except Exception as exc:
        raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    text = response.text or ""
    pt = None
    ct = None
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        pt = getattr(response.usage_metadata, "prompt_token_count", None)
        ct = getattr(response.usage_metadata, "candidates_token_count", None)

    return LLMCallResult(text=text, prompt_tokens=pt, completion_tokens=ct)


# ══════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════


def _parse_llm_response(parsed: dict) -> ExtractionResult:
    """Convert structured JSON from the LLM into an ExtractionResult."""
    return ExtractionResult(
        text_blocks=[TextBlock(text=t) for t in parsed.get("text_blocks", []) if t.strip()],
        tables=[TableBlock(markdown=t) for t in parsed.get("tables", []) if t.strip()],
        images=[ImageBlock(caption=img.get("caption", "")) for img in parsed.get("images", []) if img.get("caption", "").strip()],
    )


def _replace_page_chunks(db: Session, page: Page, result: ExtractionResult) -> None:
    """Delete old chunks and insert new ones from LLM result."""
    for c in db.query(Chunk).filter(Chunk.page_id == page.id).all():
        db.delete(c)
    db.flush()

    ro = 0
    for tb in result.text_blocks:
        db.add(Chunk(page_id=page.id, chunk_type=ChunkType.TEXT, text=tb.text, reading_order=ro, review_status=ChunkReviewStatus.PENDING)); ro += 1
    for tab in result.tables:
        db.add(Chunk(page_id=page.id, chunk_type=ChunkType.TABLE, table_markdown=tab.markdown, reading_order=ro, review_status=ChunkReviewStatus.PENDING)); ro += 1
    for img in result.images:
        db.add(Chunk(page_id=page.id, chunk_type=ChunkType.IMAGE, image_caption=img.caption, reading_order=ro, review_status=ChunkReviewStatus.PENDING)); ro += 1
    db.flush()
    logger.info("LLM Review complete for page %d.", page_id)