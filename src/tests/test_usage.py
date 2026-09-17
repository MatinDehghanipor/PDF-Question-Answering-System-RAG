"""Integration tests for token usage endpoints (Phase 10).

Covers:
    - GET /usage                        (paginated list)
    - GET /usage/queries/{query_id}     (per-query, 404 for other users)
    - GET /usage/pages/{page_id}        (per-page,  404 for other users)
    - GET /usage/summary                (aggregate, grouping, filtering)
    - Error cases: unsupported group_by -> 422
    - Edge cases: empty history returns zeros, not errors
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_SUFFIX = uuid.uuid4().hex[:8]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _username(suffix: str) -> str:
    return f"usage_{suffix}"


async def _create_user_and_login(client: AsyncClient, suffix: str) -> str:
    username = _username(suffix)
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


async def _upload_minimal_pdf(client: AsyncClient, headers: dict, filename: str = "test.pdf") -> int:
    """Upload a single-page real PDF and return the document id."""
    import fitz
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page.insert_text((72, 72), "Usage test content.", fontsize=12)
    pdf_bytes = io.BytesIO()
    pdf_doc.save(pdf_bytes)
    pdf_doc.close()
    raw = pdf_bytes.getvalue()
    resp = await client.post(
        "/documents",
        files=[("files", (filename, raw, "application/pdf"))],
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()["documents"][0]["id"]


async def _wait_for_status(client: AsyncClient, headers: dict, doc_id: int, target: str, *, timeout: float = 60.0) -> dict:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(f"/documents/{doc_id}", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if data["status"] == target:
                return data
        await asyncio.sleep(0.5)
    pytest.fail(f"Document {doc_id} never reached '{target}' within {timeout}s")


async def _approve_all_pages(client: AsyncClient, headers: dict, doc_id: int) -> None:
    """Approve all pending pages via the approve-all endpoint."""
    resp = await client.post(
        f"/documents/{doc_id}/approve-all",
        headers=headers,
    )
    resp.raise_for_status()


async def _run_rag_query(client: AsyncClient, headers: dict, question: str = "test query") -> dict:
    """Run a RAG query with a fake LLM to avoid real API calls."""
    from app.services import llm_service
    from app.services.llm_service import LLMCallResult

    original = llm_service.call_text_llm

    def _fake_llm(prompt: str, model: str) -> LLMCallResult:
        return LLMCallResult(
            text="Fake answer about artificial intelligence.",
            prompt_tokens=50,
            completion_tokens=10,
        )

    llm_service.call_text_llm = _fake_llm
    try:
        resp = await client.post(
            "/query/",
            json={"text": question, "k_value": 1, "mode": "rag"},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        llm_service.call_text_llm = original


async def _run_raw_query(client: AsyncClient, headers: dict, doc_id: int, question: str = "raw test") -> dict:
    """Run a Raw Mode query with a fake LLM to avoid real API calls."""
    from app.services import llm_service
    from app.services.llm_service import LLMCallResult

    original = llm_service.call_text_llm_with_files

    def _fake_llm_with_files(prompt: str, file_paths: list[str], model: str) -> LLMCallResult:
        return LLMCallResult(
            text="Fake answer for raw mode query.",
            prompt_tokens=60,
            completion_tokens=15,
        )

    llm_service.call_text_llm_with_files = _fake_llm_with_files
    try:
        resp = await client.post(
            "/query/",
            json={"text": question, "mode": "raw", "document_ids": [doc_id]},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        llm_service.call_text_llm_with_files = original


async def _setup_user(client: AsyncClient, suffix: str) -> dict:
    """Register + login, return auth headers."""
    token = await _create_user_and_login(client, suffix)
    return {"Authorization": f"Bearer {token}"}


async def _setup_user_and_doc(client: AsyncClient, suffix: str) -> tuple[dict, int]:
    """Register, login, upload + approve a document. Returns (headers, doc_id)."""
    headers = await _setup_user(client, suffix)
    doc_id = await _upload_minimal_pdf(client, headers)
    # Wait for processing to complete and status becomes awaiting_feedback
    await _wait_for_status(client, headers, doc_id, "awaiting_feedback", timeout=60.0)
    # Approve all pages — the document becomes ready synchronously
    await _approve_all_pages(client, headers, doc_id)
    # Confirm ready
    await _wait_for_status(client, headers, doc_id, "ready", timeout=60.0)
    return headers, doc_id


async def _setup_user_and_query(client: AsyncClient, suffix: str) -> tuple[dict, int, dict]:
    """Register, login, upload+approve, run RAG query. Returns (headers, doc_id, query_resp)."""
    headers, doc_id = await _setup_user_and_doc(client, suffix)
    query_resp = await _run_rag_query(client, headers)
    return headers, doc_id, query_resp


async def _setup_user_and_raw_query(client: AsyncClient, suffix: str) -> tuple[dict, int, dict]:
    """Register, login, upload+approve, run Raw query. Returns (headers, doc_id, query_resp)."""
    headers, doc_id = await _setup_user_and_doc(client, suffix)
    query_resp = await _run_raw_query(client, headers, doc_id)
    return headers, doc_id, query_resp
# ------------------------------------------------------------------
# Tests: list endpoint
# ------------------------------------------------------------------


class TestListUsage:
    """GET /usage -- paginated token usage list."""

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _setup_user(client, f"{_SUFFIX}_empty")
            resp = await client.get("/usage", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_after_query(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, _doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_list")
            resp = await client.get("/usage", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) >= 1
            for record in data:
                assert "total_tokens" in record
                assert record["context_type"] in ("query", "llm_review")

    @pytest.mark.asyncio
    async def test_list_pagination(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, _doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_pagin")
            resp = await client.get("/usage?skip=0&limit=5", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) <= 5


# ------------------------------------------------------------------
# Tests: per-query endpoint
# ------------------------------------------------------------------


class TestPerQuery:
    """GET /usage/queries/{query_id}."""

    @pytest.mark.asyncio
    async def test_valid_query(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, _doc_id, query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_query")
            query_id = query_resp["id"]
            resp = await client.get(f"/usage/queries/{query_id}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) >= 1
            record = data[0]
            assert "prompt_tokens" in record
            assert "completion_tokens" in record
            assert "total_tokens" in record
            assert record["context_type"] == "query"

    @pytest.mark.asyncio
    async def test_other_users_query_returns_404(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, _doc_id, query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_q404")
            query_id = query_resp["id"]
            user2_headers = await _setup_user(client, f"{_SUFFIX}_q404_other")
            resp = await client.get(f"/usage/queries/{query_id}", headers=user2_headers)
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_query_returns_404(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _setup_user(client, f"{_SUFFIX}_q404_nx")
            resp = await client.get("/usage/queries/999999", headers=headers)
            assert resp.status_code == 404


# ------------------------------------------------------------------
# Tests: per-page endpoint
# ------------------------------------------------------------------


class TestPerPage:
    """GET /usage/pages/{page_id}."""

    @pytest.mark.asyncio
    async def test_valid_page(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, doc_id = await _setup_user_and_doc(client, f"{_SUFFIX}_page")
            doc_resp = await client.get(f"/documents/{doc_id}", headers=headers)
            doc = doc_resp.json()
            assert len(doc["pages"]) >= 1
            page_id = doc["pages"][0]["id"]
            resp = await client.get(f"/usage/pages/{page_id}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_other_users_page_returns_404(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            user1_headers, doc_id = await _setup_user_and_doc(client, f"{_SUFFIX}_pg404")
            doc_resp = await client.get(f"/documents/{doc_id}", headers=user1_headers)
            doc = doc_resp.json()
            page_id = doc["pages"][0]["id"]
            user2_headers = await _setup_user(client, f"{_SUFFIX}_pg404_other")
            resp = await client.get(f"/usage/pages/{page_id}", headers=user2_headers)
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_page_returns_404(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _setup_user(client, f"{_SUFFIX}_pg404_nx")
            resp = await client.get("/usage/pages/999999", headers=headers)
            assert resp.status_code == 404
# ------------------------------------------------------------------
# Tests: summary endpoint
# ------------------------------------------------------------------


class TestSummary:
    """GET /usage/summary -- aggregate endpoint."""

    @pytest.mark.asyncio
    async def test_empty_summary_returns_zeros(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _setup_user(client, f"{_SUFFIX}_sum_empty")
            resp = await client.get("/usage/summary", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_prompt_tokens"] == 0
            assert data["total_completion_tokens"] == 0
            assert data["total_tokens"] == 0
            assert data["by_group"] == []

    @pytest.mark.asyncio
    async def test_grand_totals_match_sum_of_rows(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, _doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_sum_match")
            usage_resp = await client.get("/usage", headers=headers)
            usage_records = usage_resp.json()
            expected_total = sum(r["total_tokens"] for r in usage_records)
            expected_prompt = sum(r["prompt_tokens"] for r in usage_records)
            expected_completion = sum(r["completion_tokens"] for r in usage_records)
            summary_resp = await client.get("/usage/summary", headers=headers)
            summary = summary_resp.json()
            assert summary["total_tokens"] == expected_total
            assert summary["total_prompt_tokens"] == expected_prompt
            assert summary["total_completion_tokens"] == expected_completion

    @pytest.mark.asyncio
    async def test_summary_by_day(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, _doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_day")
            resp = await client.get("/usage/summary?group_by=day", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "by_group" in data
            assert len(data["by_group"]) >= 1
            for group in data["by_group"]:
                assert "group_key" in group
                assert "total_tokens" in group
                assert len(group["group_key"]) == 10  # YYYY-MM-DD

    @pytest.mark.asyncio
    async def test_summary_by_document(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_doc")
            resp = await client.get("/usage/summary?group_by=document", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "by_group" in data
            assert len(data["by_group"]) >= 1
            doc_key = str(doc_id)
            doc_group = [g for g in data["by_group"] if g["group_key"] == doc_key]
            assert len(doc_group) == 1
            assert doc_group[0]["total_tokens"] > 0

    @pytest.mark.asyncio
    async def test_unsupported_group_by_422(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _setup_user(client, f"{_SUFFIX}_422")
            resp = await client.get("/usage/summary?group_by=invalid", headers=headers)
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_document_filter_grand_total(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_filter")
            resp = await client.get(f"/usage/summary?document_id={doc_id}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_tokens"] >= 0

    @pytest.mark.asyncio
    async def test_document_filter_with_day_group(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_fday")
            resp = await client.get(
                f"/usage/summary?group_by=day&document_id={doc_id}", headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "by_group" in data
            assert isinstance(data["by_group"], list)
            if data["by_group"]:
                assert len(data["by_group"][0]["group_key"]) == 10

    @pytest.mark.asyncio
    async def test_document_filter_with_document_group(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_fdoc")
            resp = await client.get(
                f"/usage/summary?group_by=document&document_id={doc_id}", headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "by_group" in data
            assert all(g["group_key"] == str(doc_id) for g in data["by_group"])

    @pytest.mark.asyncio
    async def test_document_filter_nonexistent(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await _setup_user(client, f"{_SUFFIX}_fnx")
            resp = await client.get("/usage/summary?document_id=999999", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_tokens"] == 0
            assert data["by_group"] == []
# ------------------------------------------------------------------
# Tests: cross-user isolation
# ------------------------------------------------------------------


class TestIsolation:
    """Per-user isolation across all usage endpoints."""

    @pytest.mark.asyncio
    async def test_user2_list_does_not_show_user1_records(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers1, _doc_id, _query_resp = await _setup_user_and_query(client, f"{_SUFFIX}_iso1")
            headers2 = await _setup_user(client, f"{_SUFFIX}_iso2")
            resp2 = await client.get("/usage", headers=headers2)
            assert resp2.status_code == 200
            assert resp2.json() == []
            resp1 = await client.get("/usage", headers=headers1)
            assert len(resp1.json()) >= 1

    @pytest.mark.asyncio
    async def test_user2_summary_shows_zeros(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await _setup_user_and_query(client, f"{_SUFFIX}_iso3")
            headers2 = await _setup_user(client, f"{_SUFFIX}_iso4")
            resp = await client.get("/usage/summary", headers=headers2)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_tokens"] == 0
            assert data["by_group"] == []


# ------------------------------------------------------------------
# Tests: raw mode query
# ------------------------------------------------------------------


class TestRawMode:
    """Token usage after Raw Mode queries."""

    @pytest.mark.asyncio
    async def test_raw_query_creates_usage(self) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers, _doc_id, query_resp = await _setup_user_and_raw_query(client, f"{_SUFFIX}_raw")
            query_id = query_resp["id"]
            resp = await client.get(f"/usage/queries/{query_id}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) >= 1
            assert data[0]["total_tokens"] > 0