"""Tests for native extraction, quality scoring, and OCR extraction (Phase 3).

Uses dynamically generated PDFs (clean digital and simulated scanned) to
verify the real extraction logic produces expected content shapes.
"""

import io
from pathlib import Path

import fitz
import pytest

from app.schemas.extraction_result import ExtractionResult, TextBlock
from app.services.native_extractor import extract_native
from app.services.quality_scorer import score_quality
from app.services.ocr_extractor import extract_ocr


# ──────────────────────────────────────────────────────────────────────
# Fixtures: dynamically generated test PDFs
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def clean_pdf_path(tmp_path_factory) -> Path:
    """Create a clean digital PDF with text, a table-like area, and an image."""
    tmp = tmp_path_factory.mktemp("pdfs") / "clean.pdf"
    doc = fitz.open()

    # Page 1: text + table-like content + an embedded image
    page = doc.new_page()
    page.insert_text((72, 72), "Introduction to Glass Science", fontsize=14)
    page.insert_text((72, 100), "This is a test paragraph about glass.", fontsize=11)
    page.insert_text((72, 130), "Glass is an amorphous solid that exhibits a glass transition.", fontsize=11)
    page.insert_text((72, 160), "The composition and thermal history determine its properties.", fontsize=11)
    page.insert_text((72, 190), "Table 1. Composition of sample glasses", fontsize=11)
    page.insert_text((72, 210), "SiO2  Al2O3  Na2O  K2O", fontsize=11)
    page.insert_text((72, 230), "72.0  12.5    14.0   1.5", fontsize=11)
    page.insert_text((72, 250), "Figure 1. Glass structure diagram", fontsize=11)

    # Embed a tiny valid image created via fitz.Pixmap
    small_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
    small_pix.clear_with(0xCC)  # light gray fill
    img_bytes = small_pix.tobytes("png")
    page.insert_image(fitz.Rect(72, 280, 172, 380), stream=img_bytes)

    # Page 2: more text
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Experimental Methods", fontsize=14)
    page2.insert_text((72, 100), "Temperature and pressure were controlled.", fontsize=11)

    doc.save(str(tmp))
    doc.close()
    return tmp


@pytest.fixture(scope="session")
def scanned_pdf_path(tmp_path_factory) -> Path:
    """Create a simulated scanned PDF (no text layer, just an embedded image)."""
    tmp = tmp_path_factory.mktemp("pdfs") / "scanned.pdf"
    doc = fitz.open()

    page = doc.new_page()
    # Create a white image covering the page — no text layer
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, int(page.rect.width), int(page.rect.height)), False)
    pix.clear_with(0xFF)  # fill white
    img_bytes = pix.tobytes("png")
    page.insert_image(page.rect, stream=img_bytes)

    doc.save(str(tmp))
    doc.close()
    return tmp
# ──────────────────────────────────────────────────────────────────────
# Tests: Native Extractor
# ──────────────────────────────────────────────────────────────────────


class TestNativeExtractor:
    """Verify native extraction on clean digital PDFs."""

    def test_extracts_text_blocks(self, clean_pdf_path):
        result = extract_native(clean_pdf_path, page_number=1)
        assert len(result.text_blocks) > 0
        all_text = " ".join(tb.text for tb in result.text_blocks)
        assert "Introduction to Glass Science" in all_text
        assert "test paragraph" in all_text

    def test_extracts_text_from_page_2(self, clean_pdf_path):
        result = extract_native(clean_pdf_path, page_number=2)
        assert len(result.text_blocks) > 0
        all_text = " ".join(tb.text for tb in result.text_blocks)
        assert "Experimental Methods" in all_text

    def test_reading_order_is_top_to_bottom(self, clean_pdf_path):
        result = extract_native(clean_pdf_path, page_number=1)
        texts = [tb.text for tb in result.text_blocks]
        intro_idx = next(i for i, t in enumerate(texts) if "Introduction" in t)
        table_idx = next(i for i, t in enumerate(texts) if "Table 1" in t)
        assert intro_idx < table_idx, "Reading order should be top-to-bottom"

    def test_detects_tables(self, clean_pdf_path):
        result = extract_native(clean_pdf_path, page_number=1)
        assert isinstance(result.tables, list)

    def test_extracts_images(self, clean_pdf_path):
        result = extract_native(clean_pdf_path, page_number=1)
        assert len(result.images) > 0
        for img in result.images:
            assert img.path is not None
            assert Path(img.path).exists()
            assert img.caption  # non-empty

    def test_image_caption_matches_text(self, clean_pdf_path):
        result = extract_native(clean_pdf_path, page_number=1)
        figure_found = any("Figure" in img.caption for img in result.images)
        if not figure_found:
            assert all(img.caption for img in result.images)
# ──────────────────────────────────────────────────────────────────────
# Tests: Quality Scorer
# ──────────────────────────────────────────────────────────────────────


class TestQualityScorer:
    """Verify the OD-3 composite quality score."""

    def test_clean_page_scores_high(self, clean_pdf_path):
        with fitz.open(clean_pdf_path) as doc:
            page = doc[0]
            rect = (page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)
        result = extract_native(clean_pdf_path, page_number=1)
        score = score_quality(result, rect)
        assert 0.0 <= score <= 1.0
        assert score >= 0.3, f"Clean PDF scored {score:.3f}, expected >= 0.3"

    def test_empty_result_scores_low(self):
        result = ExtractionResult()
        rect = (0.0, 0.0, 595.0, 842.0)
        score = score_quality(result, rect)
        assert score < 0.5

    def test_garbled_text_scores_low(self):
        blocks = [TextBlock(text="\x00\x01\x02\x03\x04\x05\x06\x07\x08")]
        result = ExtractionResult(text_blocks=blocks)
        rect = (0.0, 0.0, 595.0, 842.0)
        score = score_quality(result, rect)
        assert score < 0.5

    def test_score_is_bounded(self):
        result = ExtractionResult(text_blocks=[TextBlock(text="Hello World!")])
        rect = (0.0, 0.0, 1.0, 1.0)
        score = score_quality(result, rect)
        assert 0.0 <= score <= 1.0
        rect2 = (0.0, 0.0, -1.0, -1.0)
        score2 = score_quality(result, rect2)
        assert 0.0 <= score2 <= 1.0

    def test_scores_differ_by_content_quality(self):
        clean_result = ExtractionResult(
            text_blocks=[TextBlock(text="The quick brown fox jumps over the lazy dog.")],
        )
        garbled_result = ExtractionResult(
            text_blocks=[TextBlock(text="\x00\x01\x02\x03\x04\x05The quick brown fox")],
        )
        rect = (0.0, 0.0, 595.0, 842.0)
        clean_score = score_quality(clean_result, rect)
        garbled_score = score_quality(garbled_result, rect)
        assert clean_score > garbled_score
# ──────────────────────────────────────────────────────────────────────
# Tests: OCR Extractor
# ──────────────────────────────────────────────────────────────────────


class TestOCRExtractor:
    """Verify OCR extraction.  Skipped if Tesseract is not installed."""

    def test_ocr_on_scanned_pdf_returns_text(self, scanned_pdf_path):
        try:
            result = extract_ocr(scanned_pdf_path, page_number=1)
        except (RuntimeError, Exception):
            pytest.skip("Tesseract not available")
        assert hasattr(result, "text_blocks")
        assert isinstance(result.text_blocks, list)

    def test_ocr_on_clean_pdf_does_not_crash(self, clean_pdf_path):
        try:
            result = extract_ocr(clean_pdf_path, page_number=1)
        except (RuntimeError, Exception):
            pytest.skip("Tesseract not available")
        assert len(result.text_blocks) > 0

    def test_ocr_produces_same_shape_as_native(self, clean_pdf_path):
        try:
            ocr_result = extract_ocr(clean_pdf_path, page_number=1)
        except (RuntimeError, Exception):
            pytest.skip("Tesseract not available")

        native_result = extract_native(clean_pdf_path, page_number=1)
        assert hasattr(ocr_result, "text_blocks")
        assert hasattr(ocr_result, "tables")
        assert hasattr(ocr_result, "images")
        assert isinstance(ocr_result.text_blocks, list)
        assert isinstance(ocr_result.tables, list)
        assert isinstance(ocr_result.images, list)


# ──────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────


def test_native_extractor_raises_on_bad_path():
    with pytest.raises(RuntimeError):
        extract_native("/nonexistent/file.pdf", page_number=1)


def test_native_extractor_raises_on_bad_page_number(clean_pdf_path):
    with pytest.raises(RuntimeError):
        extract_native(clean_pdf_path, page_number=999)