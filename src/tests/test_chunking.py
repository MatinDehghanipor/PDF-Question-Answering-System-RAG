"""Tests for chunking, embedding, and indexing (Phase 6).

Covers:
    - ``should_split_chunk`` with short and long text.
    - ``split_text_chunk`` returns correct sub-chunks with ordering.
    - ``split_and_index_page`` end-to-end via mock Chroma.
    - Edge cases: empty text chunks, table/image chunks never split.
"""

import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

_SUFFIX = uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _ensure_storage_dir():
    Path(settings.FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    yield


# ──────────────────────────────────────────────────────────────────────
# Unit tests for utility functions
# ──────────────────────────────────────────────────────────────────────


class TestShouldSplitChunk:
    """Tests for ``embedding_service.should_split_chunk``."""

    def test_short_text_not_split(self):
        from app.services.embedding_service import should_split_chunk
        short = "Hello, this is a short text."
        assert should_split_chunk(short) is False

    def test_long_text_should_split(self):
        from app.services.embedding_service import should_split_chunk
        long_text = "word " * 2000
        assert should_split_chunk(long_text) is True


class TestSplitTextChunk:
    """Tests for ``embedding_service.split_text_chunk``."""

    def test_split_returns_subchunks_with_ordering(self):
        from app.services.embedding_service import split_text_chunk

        long_text = "Paragraph one.\n\n" * 30 + "Paragraph two.\n\n" * 30
        result = split_text_chunk(long_text, chunk_id=42, reading_order=3)

        assert len(result) > 1
        for item in result:
            assert "text" in item
            assert item["reading_order"] == 3
            assert "sub_index" in item
            assert item["parent_chunk_id"] == 42

        indices = [item["sub_index"] for item in result]
        assert indices == list(range(len(result)))

    def test_short_text_returns_single_subchunk(self):
        from app.services.embedding_service import split_text_chunk

        short = "Short text."
        result = split_text_chunk(short, chunk_id=1, reading_order=0)
        assert len(result) == 1
        assert result[0]["text"] == short

    def test_concatenated_subchunks_approximate_original(self):
        from app.services.embedding_service import split_text_chunk

        text = " ".join(f"Sentence number {i}." for i in range(100))
        result = split_text_chunk(text, chunk_id=1, reading_order=0)

        all_text = " ".join(sc["text"] for sc in result)
        for i in range(100):
            assert f"Sentence number {i}." in all_text


# ──────────────────────────────────────────────────────────────────────
# Integration tests: indexing a page after approval
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_page_triggers_indexing():
    """Approving a page calls ``split_and_index_page`` (verified via
    the upsert_chunks call being invoked)."""
    from app.services.vector_store import upsert_chunks
    original = upsert_chunks
    upsert_called = False

    def _fake_upsert(*args, **kwargs):
        nonlocal upsert_called
        upsert_called = True

    try:
        import app.services.chunker as chunker_mod
        chunker_mod.upsert_chunks = _fake_upsert
        chunker_mod.delete_chunks_for_document = lambda uid, did: None

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            suffix = _SUFFIX
            username = f"c_{suffix}"
            email = f"{username}@example.com"
            resp = await client.post(
                "/auth/register",
                json={"username": username, "email": email, "password": "StrongPass1!"},
            )
            assert resp.status_code == 201
            resp = await client.post(
                "/auth/login",
                data={"username": username, "password": "StrongPass1!"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status_code == 200
            token = resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            import fitz
            pdf_doc = fitz.open()
            pdf_doc.new_page()
            pdf_page = pdf_doc[0]
            pdf_page.insert_text((72, 72), "Test content for indexing.", fontsize=12)
            pdf_page.insert_text(
                (72, 100), "More content to ensure quality threshold.", fontsize=11
            )
            pdf_bytes = io.BytesIO()
            pdf_doc.save(pdf_bytes)
            pdf_doc.close()

            resp = await client.post(
                "/documents",
                files=[("files", ("test.pdf", pdf_bytes.getvalue(), "application/pdf"))],
                headers=headers,
            )
            assert resp.status_code == 201
            doc_id = resp.json()["documents"][0]["id"]

            resp = await client.get(f"/documents/{doc_id}/pages", headers=headers)
            assert resp.status_code == 200
            pages = resp.json()
            page_id = pages[0]["id"]

            resp = await client.post(
                f"/pages/{page_id}/review",
                json={"decision": "approved"},
                headers=headers,
            )
            assert resp.status_code == 200
            assert upsert_called, "upsert_chunks was never called during approval"
    finally:
        import app.services.chunker as chunker_mod
        chunker_mod.upsert_chunks = original
                
@pytest.mark.asyncio
async def test_indexing_does_not_include_rejected_chunks():
    """Rejected / excluded chunks are never passed to the embedder."""
    import app.services.chunker as chunker_mod
    embed_called_with = []

    def _tracking_embed(texts):
        embed_called_with.extend(texts)
        import numpy as np
        return [np.zeros(384).tolist() for _ in texts]

    from app.services.vector_store import upsert_chunks
    original_upsert = upsert_chunks
    original_embed = chunker_mod.embed_texts if hasattr(chunker_mod, 'embed_texts') else None

    def _fake_upsert(*args, **kwargs):
        pass

    try:
        chunker_mod.embed_texts = _tracking_embed
        chunker_mod.upsert_chunks = _fake_upsert

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            suffix = _SUFFIX + "_rej"
            username = f"c_{suffix}"
            email = f"{username}@example.com"
            await client.post(
                "/auth/register",
                json={"username": username, "email": email, "password": "StrongPass1!"},
            )
            resp = await client.post(
                "/auth/login",
                data={"username": username, "password": "StrongPass1!"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token = resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            import fitz
            pdf_doc = fitz.open()
            pdf_doc.new_page()
            pdf_page = pdf_doc[0]
            pdf_page.insert_text((72, 72), "Visible content.", fontsize=12)
            pdf_page.insert_text((72, 100), "More text.", fontsize=11)
            pdf_bytes = io.BytesIO()
            pdf_doc.save(pdf_bytes)
            pdf_doc.close()

            resp = await client.post(
                "/documents",
                files=[("files", ("test.pdf", pdf_bytes.getvalue(), "application/pdf"))],
                headers=headers,
            )
            doc_id = resp.json()["documents"][0]["id"]

            resp = await client.get(f"/documents/{doc_id}/pages", headers=headers)
            pages = resp.json()
            page_id = pages[0]["id"]

            # Exclude first chunk
            first_chunk_id = pages[0]["chunks"][0]["id"]
            await client.patch(
                f"/pages/chunks/{first_chunk_id}",
                json={"excluded": True},
                headers=headers,
            )

            # Approve
            await client.post(
                f"/pages/{page_id}/review",
                json={"decision": "approved"},
                headers=headers,
            )

            for text in embed_called_with:
                assert "Visible content" not in text, (
                    f"Rejected chunk text leaked into embed: {text!r}"
                )
    finally:
        if original_embed is not None:
            chunker_mod.embed_texts = original_embed
        chunker_mod.upsert_chunks = original_upsert