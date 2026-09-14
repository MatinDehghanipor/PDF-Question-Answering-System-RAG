"""Shared extraction result types for the PDF QA system.

Defines the typed block structures (TextBlock, TableBlock, ImageBlock) and the
aggregate ExtractionResult dataclass that ALL three extractors produce
(native_extractor, ocr_extractor, and in Phase 5, llm_review).  Downstream
code (chunking, review, indexing) is extractor-agnostic per SDD §2.2.

All three extraction methods produce the same three content types, so the
pipeline never needs to know which method produced a given page's content.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TextBlock:
    """A single text block extracted from a page.

    Attributes:
        text: The plain text content.
        bbox: Bounding box as (x0, y0, x1, y1) in PDF points (1/72 inch).
    """

    text: str
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class TableBlock:
    """A table detected on a page, serialized to Markdown (FR-18).

    Attributes:
        markdown: Markdown-table representation of the table.
        bbox: Bounding box as (x0, y0, x1, y1) in PDF points (from Camelot).
    """

    markdown: str
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class ImageBlock:
    """An image extracted from a page with its indexable caption (FR-19).

    Attributes:
        caption: The image caption/description (matched via proximity, or the
            OD-4 placeholder).  LLM Review (Phase 5) will produce higher-
            quality captions via vision LLM for pages that reach that fallback.
        path: Filesystem path to the saved image file.
        bbox: Bounding box as (x0, y0, x1, y1) in PDF points.
    """

    caption: str = ""
    path: str | None = None
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class ExtractionResult:
    """Structured content extracted from a single PDF page (SDD §2.2).

    Attributes:
        text_blocks: Plain-text blocks extracted from the page, in approximate
            reading order (top-to-bottom, left-to-right).
        tables: Table blocks serialized to Markdown.
        images: Image blocks with captions and file paths.
    """

    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    images: list[ImageBlock] = field(default_factory=list)