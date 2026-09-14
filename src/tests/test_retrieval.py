"""Tests for the retrieval service (Phase 7).

Covers:
    - ``retrieve_top_k`` returns typed ``RetrievedChunk`` objects.
    - Chunks from the same page appear in reading order (FR-26).
    - Chunks from two different documents are grouped by document in the
      prompt (OD-6), not interleaved.
    - The document with the single highest-scoring (lowest-distance) chunk
      appears first (OD-6).
    - Empty retrieval returns an empty list without error.
    - k larger than available chunks returns all available.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List
from unittest.mock import ANY, MagicMock, patch

import pytest
from app.core.config import settings
from app.services.retrieval_service import RetrievedChunk, retrieve_top_k
from app.services.vector_store import top_k_search


# ──────────────────────────────────────────────────────────────────────────
# Fixtures: seeded "vector store" results
# ──────────────────────────────────────────────────────────────────────────


def _make_raw_chunk(
    chunk_id: str,
    text: str,
    doc_id: int,
    doc_filename: str,
    page_id: int,
    page_number: int,
    reading_order: int,
    sub_index: int = 0,
    chunk_type: str = "text",
    distance: float = 0.5,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "document": text,
        "metadata": {
            "document_id": doc_id,
            "document_filename": doc_filename,
            "page_id": page_id,
            "page_number": page_number,
            "chunk_type": chunk_type,
            "reading_order": reading_order,
            "sub_index": sub_index,
        },
        "distance": distance,
    }


def _make_query_vector() -> list[float]:
    """Return a dummy 384‑dim vector (matching all-MiniLM-L6-v2)."""
    return [0.0] * 384


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestRetrieveTopK:
    """Tests for ``retrieve_top_k`` with a mocked Chroma search."""

    @patch("app.services.retrieval_service.top_k_search")
    def test_returns_retrieved_chunk_type(self, mock_search):
        """Each returned item is a ``RetrievedChunk`` with expected fields."""
        mock_search.return_value = [
            _make_raw_chunk("chunk_1", "Hello world", 10, "doc.pdf", 1, 1, 0),
        ]

        results = retrieve_top_k(user_id=1, query_text="hello", k=5)
        assert len(results) == 1
        rc = results[0]
        assert isinstance(rc, RetrievedChunk)
        assert rc.chunk_id == "chunk_1"
        assert rc.text_or_caption == "Hello world"
        assert rc.document_id == 10
        assert rc.document_filename == "doc.pdf"
        assert rc.page_number == 1
        assert rc.reading_order == 0
        assert rc.distance == 0.5

    @patch("app.services.retrieval_service.top_k_search")
    def test_similarity_score_higher_is_better(self, mock_search):
        """``similarity_score`` is ``1 - distance`` so higher = more similar."""
        mock_search.return_value = [
            _make_raw_chunk("c1", "a", 1, "f.pdf", 1, 1, 0, distance=0.2),
            _make_raw_chunk("c2", "b", 1, "f.pdf", 1, 1, 1, distance=0.8),
        ]
        results = retrieve_top_k(user_id=1, query_text="q", k=5)
        assert results[0].similarity_score == pytest.approx(0.8)
        assert results[1].similarity_score == pytest.approx(0.2)

    @patch("app.services.retrieval_service.top_k_search")
    def test_reading_order_within_same_page(self, mock_search):
        """Chunks from the same page appear in (reading_order, sub_index) order."""
        mock_search.return_value = [
            # Insert out of order to verify sorting
            _make_raw_chunk("c3", "Third", 1, "f.pdf", 1, 1, 2),
            _make_raw_chunk("c1", "First", 1, "f.pdf", 1, 1, 0),
            _make_raw_chunk("c2", "Second", 1, "f.pdf", 1, 1, 1),
        ]
        results = retrieve_top_k(user_id=1, query_text="q", k=5)
        texts = [rc.text_or_caption for rc in results]
        assert texts == ["First", "Second", "Third"]

    @patch("app.services.retrieval_service.top_k_search")
    def test_sub_index_order_within_same_reading_order(self, mock_search):
        """Sub-chunks (same reading_order) are ordered by sub_index ascending."""
        mock_search.return_value = [
            _make_raw_chunk("c1_sub2", "Part 3", 1, "f.pdf", 1, 1, 0, sub_index=2),
            _make_raw_chunk("c1_sub0", "Part 1", 1, "f.pdf", 1, 1, 0, sub_index=0),
            _make_raw_chunk("c1_sub1", "Part 2", 1, "f.pdf", 1, 1, 0, sub_index=1),
        ]
        results = retrieve_top_k(user_id=1, query_text="q", k=5)
        texts = [rc.text_or_caption for rc in results]
        assert texts == ["Part 1", "Part 2", "Part 3"]

    @patch("app.services.retrieval_service.top_k_search")
    def test_two_documents_grouped_not_interleaved(self, mock_search):
        """Chunks from different docs are grouped contiguously (OD-6)."""
        mock_search.return_value = [
            _make_raw_chunk("d1c1", "Doc1 A", 1, "alpha.pdf", 1, 1, 0, distance=0.1),
            _make_raw_chunk("d2c1", "Doc2 A", 2, "beta.pdf", 1, 1, 0, distance=0.5),
            _make_raw_chunk("d1c2", "Doc1 B", 1, "alpha.pdf", 1, 1, 1, distance=0.2),
            _make_raw_chunk("d2c2", "Doc2 B", 2, "beta.pdf", 1, 1, 1, distance=0.6),
        ]
        results = retrieve_top_k(user_id=1, query_text="q", k=5)

        # Doc 1 has the lowest-minimum-distance (0.1), so it comes first.
        doc_ids = [rc.document_id for rc in results]
        # Expect first two from doc 1, then next two from doc 2
        assert doc_ids == [1, 1, 2, 2]

    @patch("app.services.retrieval_service.top_k_search")
    def test_highest_similarity_document_first(self, mock_search):
        """Document with lowest min-distance chunk appears first (OD-6)."""
        mock_search.return_value = [
            _make_raw_chunk("d2_best", "Doc2 most relevant", 2, "beta.pdf", 1, 1, 0, distance=0.05),
            _make_raw_chunk("d1_worst", "Doc1 less relevant", 1, "alpha.pdf", 1, 1, 0, distance=0.4),
            _make_raw_chunk("d2_other", "Doc2 other", 2, "beta.pdf", 1, 1, 1, distance=0.3),
            _make_raw_chunk("d1_other", "Doc1 other", 1, "alpha.pdf", 1, 1, 1, distance=0.5),
        ]
        results = retrieve_top_k(user_id=1, query_text="q", k=5)
        # Doc 2 (min-distance=0.05) should come before Doc 1 (min-distance=0.4)
        doc_ids = [rc.document_id for rc in results]
        assert doc_ids == [2, 2, 1, 1]

    @patch("app.services.retrieval_service.top_k_search")
    def test_empty_returns_empty_list(self, mock_search):
        """Search returning no results yields an empty list, not an error."""
        mock_search.return_value = []
        results = retrieve_top_k(user_id=1, query_text="nonexistent", k=5)
        assert results == []

    @patch("app.services.retrieval_service.top_k_search")
    def test_fewer_than_k_is_not_error(self, mock_search):
        """If only 2 chunks exist, requesting k=10 returns 2."""
        mock_search.return_value = [
            _make_raw_chunk("c1", "Only", 1, "f.pdf", 1, 1, 0),
            _make_raw_chunk("c2", "Two", 1, "f.pdf", 1, 1, 1),
        ]
        results = retrieve_top_k(user_id=1, query_text="q", k=10)
        assert len(results) == 2


class TestPromptBuilder:
    """Tests for ``build_rag_prompt`` — chunk ordering in the prompt string."""

    def _make_chunk(self, doc_id=1, filename="report.pdf", page=1, ro=0, sub=0, text="Text.") -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=f"chunk_{doc_id}_{ro}",
            document_id=doc_id,
            document_filename=filename,
            page_id=page,
            page_number=page,
            chunk_type="text",
            text_or_caption=text,
            reading_order=ro,
            sub_index=sub,
            distance=0.5,
        )

    def test_prompt_contains_all_chunks(self):
        from app.services.prompt_builder import build_rag_prompt

        chunks = [
            self._make_chunk(ro=0, text="First"),
            self._make_chunk(ro=1, text="Second"),
        ]
        prompt = build_rag_prompt("my question", chunks)
        assert "First" in prompt
        assert "Second" in prompt
        assert "my question" in prompt

    def test_prompt_shows_document_header(self):
        from app.services.prompt_builder import build_rag_prompt

        chunks = [
            self._make_chunk(filename="my_doc.pdf", page=3, ro=0, text="Content"),
        ]
        prompt = build_rag_prompt("q", chunks)
        assert "my_doc.pdf" in prompt
        assert "[Page 3]" in prompt

    def test_reading_order_in_prompt(self):
        """Chunks inserted out of reading order appear correctly in the prompt."""
        from app.services.prompt_builder import build_rag_prompt

        chunks = [
            self._make_chunk(ro=2, text="Third"),
            self._make_chunk(ro=0, text="First"),
            self._make_chunk(ro=1, text="Second"),
        ]
        prompt = build_rag_prompt("q", chunks)
        first_idx = prompt.index("First")
        second_idx = prompt.index("Second")
        third_idx = prompt.index("Third")
        assert first_idx < second_idx < third_idx

    def test_two_documents_grouped_in_prompt(self):
        """Prompt shows Document A's chunks together, then Document B's."""
        from app.services.prompt_builder import build_rag_prompt

        chunks = [
            self._make_chunk(doc_id=2, filename="B.pdf", ro=0, text="B1"),
            self._make_chunk(doc_id=1, filename="A.pdf", ro=0, text="A1"),
            self._make_chunk(doc_id=1, filename="A.pdf", ro=1, text="A2"),
        ]
        prompt = build_rag_prompt("q", chunks)

        # Doc 1 (A.pdf) has lower min-distance, so appears first
        a_section = prompt.index("--- Document: A.pdf ---")
        b_section = prompt.index("--- Document: B.pdf ---")
        a1_idx = prompt.index("A1")
        a2_idx = prompt.index("A2")
        b1_idx = prompt.index("B1")

        assert a_section < b_section
        # A's chunks together
        assert a1_idx < a2_idx
        # B's section after A's last chunk
        assert a2_idx < b_section

    def test_empty_chunks_shows_no_excerpts_note(self):
        from app.services.prompt_builder import build_rag_prompt

        prompt = build_rag_prompt("q", [])
        assert "No relevant excerpts" in prompt
        assert "q" in prompt
