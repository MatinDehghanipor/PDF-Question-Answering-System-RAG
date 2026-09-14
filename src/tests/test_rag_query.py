"""Integration tests for POST /query (RAG Mode) — Phase 7.

Covers:
    - Request with no `ready` documents returns 400.
    - Request with `k` outside [1, 20] returns 422.
    - Successful RAG query returns AnswerOut with mode="rag", sources,
      and token_usage (mocking the LLM call).
    - Raw Mode returns 501 (Phase 8 not yet implemented).
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

_SUFFIX = uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _ensure_storage_dir():
    Path(settings.FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    yield


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


async def _create_user_and_login(client: AsyncClient, suffix: str) -> str:
    """Register + login, return bearer token."""
    username = f"rag_{suffix}"
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
    return resp.json()["access_token"]


async def _upload_and_approve_pdf(client: AsyncClient, headers: dict) -> int:
    """Upload a minimal PDF, wait for processing, approve all pages, return doc id."""
    import fitz
    pdf_doc = fitz.open()
    pdf_doc.new_page()
    page = pdf_doc[0]
    page.insert_text((72, 72), "RAG test content about artificial intelligence.", fontsize=12)
    page.insert_text((72, 100), "Machine learning is a subset of AI.", fontsize=11)
    pdf_bytes = io.BytesIO()
    pdf_doc.save(pdf_bytes)
    pdf_doc.close()

    resp = await client.post(
        "/documents",
        files=[("files", ("rag_test.pdf", pdf_bytes.getvalue(), "application/pdf"))],
        headers=headers,
    )
    doc_id = resp.json()["documents"][0]["id"]

    # Wait for processing to finish (status pole)
    import time
    for _ in range(20):
        resp = await client.get(f"/documents/{doc_id}", headers=headers)
        status = resp.json()["status"]
        if status == "awaiting_feedback":
            break
        time.sleep(0.3)
    else:
        pytest.fail("Document never reached awaiting_feedback")

    # Approve all pages
    resp = await client.post(f"/documents/{doc_id}/approve-all", headers=headers)
    assert resp.status_code == 200

    # Confirm READY
    resp = await client.get(f"/documents/{doc_id}", headers=headers)
    assert resp.json()["status"] == "ready", f"Expected ready, got {resp.json()['status']}"

    return doc_id


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestQueryValidation:
    """Precondition and input validation."""

    @pytest.mark.asyncio
    async def test_no_ready_documents_returns_400(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            token = await _create_user_and_login(client, _SUFFIX + "_no_ready")
            headers = {"Authorization": f"Bearer {token}"}

            resp = await client.post(
                "/query/",
                json={"text": "What is AI?"},
                headers=headers,
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "No Ready documents found" in data["detail"]

    @pytest.mark.asyncio
    async def test_k_out_of_range_returns_422(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            token = await _create_user_and_login(client, _SUFFIX + "_k_range")
            headers = {"Authorization": f"Bearer {token}"}

            # Below MIN_TOP_K (1)
            resp = await client.post(
                "/query/",
                json={"text": "test", "k_value": 0},
                headers=headers,
            )
            assert resp.status_code == 422

            # Above MAX_TOP_K (20)
            resp = await client.post(
                "/query/",
                json={"text": "test", "k_value": 21},
                headers=headers,
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_raw_mode_returns_501(self):
        """Raw Mode should return 501 Not Implemented (Phase 8)."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            token = await _create_user_and_login(client, _SUFFIX + "_raw_501")
            headers = {"Authorization": f"Bearer {token}"}

            resp = await client.post(
                "/query/",
                json={"text": "test", "mode": "raw"},
                headers=headers,
            )
            assert resp.status_code == 501


class TestRagQueryHappyPath:
    """Successful RAG Mode query (with LLM call mocked)."""

    @pytest.mark.asyncio
    async def test_rag_query_returns_answer_with_mode_and_sources(self):
        """A query against a ready document returns AnswerOut with all expected fields."""
        from app.services import llm_service

        original_call = llm_service.call_text_llm

        def _fake_llm(prompt: str, model: str):
            from app.services.llm_service import LLMCallResult
            return LLMCallResult(
                text="Artificial intelligence is a broad field of computer science.",
                prompt_tokens=50,
                completion_tokens=10,
            )

        llm_service.call_text_llm = _fake_llm

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                token = await _create_user_and_login(client, _SUFFIX + "_happy")
                headers = {"Authorization": f"Bearer {token}"}

                # Upload and approve a document so we have indexed chunks
                doc_id = await _upload_and_approve_pdf(client, headers)

                resp = await client.post(
                    "/query/",
                    json={"text": "What is AI?"},
                    headers=headers,
                )
                assert resp.status_code == 200, f"Body: {resp.text}"
                data = resp.json()

                # Shape checks
                assert data["mode"] == "rag"
                assert len(data["generated_text"]) > 0
                assert "Artificial intelligence" in data["generated_text"]

                # Sources should be non-empty
                assert len(data["sources"]) > 0
                for src in data["sources"]:
                    assert "document_filename" in src
                    assert "page_number" in src

                # source_chunk_ids should be present
                assert data["source_chunk_ids"] is not None
                assert len(data["source_chunk_ids"]) > 0

                # token_usage
                tu = data["token_usage"]
                assert tu is not None
                assert tu["prompt_tokens"] > 0
                assert tu["completion_tokens"] > 0
                assert tu["total_tokens"] == tu["prompt_tokens"] + tu["completion_tokens"]

                # llm_model_version
                assert data["llm_model_version"] == settings.LLM_ANSWER_MODEL

                # id and query_id are present
                assert data["id"] > 0
                assert data["query_id"] > 0
        finally:
            llm_service.call_text_llm = original_call

    @pytest.mark.asyncio
    async def test_rag_query_with_custom_k(self):
        """Explicit k_value is accepted within valid range."""
        from app.services import llm_service

        original_call = llm_service.call_text_llm

        def _fake_llm(prompt: str, model: str):
            from app.services.llm_service import LLMCallResult
            return LLMCallResult(text="Some answer.", prompt_tokens=10, completion_tokens=5)

        llm_service.call_text_llm = _fake_llm

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                token = await _create_user_and_login(client, _SUFFIX + "_cust_k")
                headers = {"Authorization": f"Bearer {token}"}
                await _upload_and_approve_pdf(client, headers)

                resp = await client.post(
                    "/query/",
                    json={"text": "AI", "k_value": 3},
                    headers=headers,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["mode"] == "rag"
                assert len(data["sources"]) > 0
        finally:
            llm_service.call_text_llm = original_call

    @pytest.mark.asyncio
    async def test_llm_failure_returns_502(self):
        """If the LLM call fails, a 502 is returned but the Query row persists."""
        from app.services import llm_service

        original_call = llm_service.call_text_llm

        def _failing_llm(prompt: str, model: str):
            raise RuntimeError("Simulated LLM failure")

        llm_service.call_text_llm = _failing_llm

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                token = await _create_user_and_login(client, _SUFFIX + "_llm_fail")
                headers = {"Authorization": f"Bearer {token}"}
                await _upload_and_approve_pdf(client, headers)

                resp = await client.post(
                    "/query/",
                    json={"text": "What is AI?"},
                    headers=headers,
                )
                assert resp.status_code == 502
                data = resp.json()
                assert "LLM answer generation failed" in data["detail"]
        finally:
            llm_service.call_text_llm = original_call
