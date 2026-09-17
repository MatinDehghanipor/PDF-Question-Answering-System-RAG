"""Integration tests for POST /query (Raw Mode) — Phase 8.

Covers:
    - mode=raw requires document_ids (422)
    - selected documents must be owned by current user (404)
    - OD-7 page-count limit rejection (413)
    - OD-7 file-size limit rejection (413), for a single oversized file and
      for several files whose sizes sum over the limit
    - successful raw query returns mode/sources/document-ids/token usage
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

_SUFFIX = uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _ensure_storage_dir():
    Path(settings.FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    yield


async def _create_user_and_login(client: AsyncClient, suffix: str) -> str:
    username = f"raw_{suffix}"
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


def _make_pdf_bytes(page_count: int = 1) -> bytes:
    """Build a minimal but real PDF with *page_count* pages.

    Kept separate from :func:`_upload_pdf` so the OD-7 file-size tests can
    measure exactly the number of bytes that will land on disk, instead of
    guessing a size and hoping the assertion stays valid.
    """
    pdf_doc = fitz.open()
    for i in range(page_count):
        page = pdf_doc.new_page()
        page.insert_text((72, 72), f"Raw test page {i + 1}", fontsize=12)
    pdf_bytes = io.BytesIO()
    pdf_doc.save(pdf_bytes)
    pdf_doc.close()
    return pdf_bytes.getvalue()


def _forbid_llm_call(*args, **kwargs):
    """Fail the test immediately if the LLM is called.

    Used by the OD-7 rejection tests: the size/page limits must be enforced
    *before* any file is uploaded to the provider, otherwise Raw Mode would pay
    the full token cost (NFR-6) for a request it is about to reject.
    """
    raise AssertionError("LLM should not be called when OD-7 limits fail")


async def _upload_pdf(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    page_count: int = 1,
    filename: str = "raw_test.pdf",
) -> int:
    resp = await client.post(
        "/documents",
        files=[("files", (filename, _make_pdf_bytes(page_count), "application/pdf"))],
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["documents"][0]["id"]


@pytest.mark.asyncio
async def test_raw_mode_document_ids_required_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _create_user_and_login(client, _SUFFIX + "_req")
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            "/query/",
            json={"text": "Summarize this", "mode": "raw"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "document_ids is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_raw_mode_other_users_document_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token_a = await _create_user_and_login(client, _SUFFIX + "_owner")
        headers_a = {"Authorization": f"Bearer {token_a}"}
        doc_id = await _upload_pdf(client, headers_a, filename="owner_only.pdf")

        token_b = await _create_user_and_login(client, _SUFFIX + "_other")
        headers_b = {"Authorization": f"Bearer {token_b}"}

        resp = await client.post(
            "/query/",
            json={"text": "What is in this file?", "mode": "raw", "document_ids": [doc_id]},
            headers=headers_b,
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_raw_mode_exceeding_page_limit_returns_413(monkeypatch):
    from app.services import llm_service

    monkeypatch.setattr(settings, "RAW_MODE_MAX_PAGES", 1)
    monkeypatch.setattr(llm_service, "call_text_llm_with_files", _forbid_llm_call)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _create_user_and_login(client, _SUFFIX + "_limit")
        headers = {"Authorization": f"Bearer {token}"}
        doc_id = await _upload_pdf(client, headers, page_count=2, filename="two_pages.pdf")

        resp = await client.post(
            "/query/",
            json={"text": "summarize", "mode": "raw", "document_ids": [doc_id]},
            headers=headers,
        )
        assert resp.status_code == 413
        assert "page count" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_raw_mode_single_oversized_file_returns_413(monkeypatch):
    """A single file larger than OD-7's ``RAW_MODE_MAX_FILE_MB`` is rejected.

    The limit is set from the real byte size of the uploaded PDF (converted to
    MB) rather than a guessed number, so the test cannot silently stop
    exercising the size check if the minimal PDF's size ever changes.
    """
    from app.services import llm_service

    monkeypatch.setattr(llm_service, "call_text_llm_with_files", _forbid_llm_call)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _create_user_and_login(client, _SUFFIX + "_size1")
        headers = {"Authorization": f"Bearer {token}"}
        doc_id = await _upload_pdf(client, headers, filename="oversized.pdf")

        pdf_mb = len(_make_pdf_bytes(1)) / (1024 * 1024)
        # Cartel the limit just below the file's real size.
        monkeypatch.setattr(settings, "RAW_MODE_MAX_FILE_MB", pdf_mb * 0.5)

        resp = await client.post(
            "/query/",
            json={"text": "summarize", "mode": "raw", "document_ids": [doc_id]},
            headers=headers,
        )
        assert resp.status_code == 413
        assert "file size" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_raw_mode_multiple_files_summing_over_limit_returns_413(monkeypatch):
    """Several individually-small files whose sizes *sum* over the limit are rejected.

    The Phase-8 spec calls this out explicitly: the size check must apply to the
    total across the selected documents, not per file, so a user cannot bypass
    the limit by splitting the same volume across many documents.
    """
    from app.services import llm_service

    monkeypatch.setattr(llm_service, "call_text_llm_with_files", _forbid_llm_call)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _create_user_and_login(client, _SUFFIX + "_size2")
        headers = {"Authorization": f"Bearer {token}"}
        doc_a = await _upload_pdf(client, headers, filename="part_a.pdf")
        doc_b = await _upload_pdf(client, headers, filename="part_b.pdf")

        # Each file alone is under the limit; together they exceed it.
        pdf_mb = len(_make_pdf_bytes(1)) / (1024 * 1024)
        monkeypatch.setattr(settings, "RAW_MODE_MAX_FILE_MB", pdf_mb * 1.5)

        resp = await client.post(
            "/query/",
            json={"text": "summarize", "mode": "raw", "document_ids": [doc_a, doc_b]},
            headers=headers,
        )
        assert resp.status_code == 413
        assert "file size" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_raw_mode_success_returns_answer_out(monkeypatch):
    from app.services import llm_service
    from app.services.llm_service import LLMCallResult

    def _fake_llm_with_files(prompt: str, file_paths: list[str], model: str) -> LLMCallResult:
        assert prompt
        assert model == settings.LLM_ANSWER_MODEL
        assert file_paths and all(Path(p).exists() for p in file_paths)
        return LLMCallResult(text="Raw answer text.", prompt_tokens=12, completion_tokens=7)

    monkeypatch.setattr(llm_service, "call_text_llm_with_files", _fake_llm_with_files)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _create_user_and_login(client, _SUFFIX + "_ok")
        headers = {"Authorization": f"Bearer {token}"}
        doc_id = await _upload_pdf(client, headers, filename="raw_success.pdf")

        resp = await client.post(
            "/query/",
            json={"text": "Please summarize.", "mode": "raw", "document_ids": [doc_id]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert data["mode"] == "raw"
        assert data["generated_text"] == "Raw answer text."
        assert data["source_chunk_ids"] is None
        assert data["source_document_ids"] == [doc_id]
        assert len(data["sources"]) == 1
        assert data["sources"][0]["document_filename"] == "raw_success.pdf"
        assert data["sources"][0]["page_number"] == 0

        tu = data["token_usage"]
        assert tu is not None
        assert tu["prompt_tokens"] == 12
        assert tu["completion_tokens"] == 7
        assert tu["total_tokens"] == 19

        # ── FR-28: Raw Mode must NOT require the UC4 "ready" precondition ──
        # The document was never approved, so RAG Mode would have rejected the
        # same request with 400.  Raw Mode answers from the original PDF, so it
        # has to succeed here — this assertion is the regression guard for that
        # deliberate difference between the two modes.
        doc_resp = await client.get(f"/documents/{doc_id}", headers=headers)
        assert doc_resp.json()["status"] != "ready", (
            "This test is only meaningful while the document is NOT ready"
        )

        _assert_raw_query_persisted(username=f"raw_{_SUFFIX}_ok", doc_id=doc_id)


def _assert_raw_query_persisted(username: str, doc_id: int) -> None:
    """Assert the Raw Mode result was persisted per FR-33 and OD-7.

    Reads the database directly (not the HTTP response) so the test proves what
    was actually written: a ``Query`` row in ``raw`` mode with no ``k_value``,
    an ``Answer`` recording the source *documents* instead of chunks, and a
    ``query``-context ``TokenUsage`` row for NFR-6/FR-33 accounting.
    """
    from app.core.database import SessionLocal
    from app.models.answer import Answer
    from app.models.enums import QueryMode, TokenUsageContextType
    from app.models.query import Query as QueryModel
    from app.models.token_usage import TokenUsage
    from app.models.user import User

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        assert user is not None, f"User '{username}' not found in the database"

        query = (
            db.query(QueryModel)
            .filter(QueryModel.user_id == user.id)
            .order_by(QueryModel.id.desc())
            .first()
        )
        assert query is not None, "No Query row was persisted for the Raw Mode request"
        assert query.mode == QueryMode.RAW
        # OD-7/FR-28: no retrieval happens in Raw Mode, so there is no top-k.
        assert query.k_value is None

        answer = db.query(Answer).filter(Answer.query_id == query.id).one_or_none()
        assert answer is not None, "No Answer row was persisted for the Raw Mode request"
        assert answer.source_document_ids == [doc_id], (
            "The Answer must record the source documents for Raw Mode (FR-30)"
        )
        assert answer.source_chunk_ids is None, "Raw Mode performs no chunk retrieval"

        usage = (
            db.query(TokenUsage)
            .filter(
                TokenUsage.user_id == user.id,
                TokenUsage.context_type == TokenUsageContextType.QUERY,
                TokenUsage.context_id == answer.id,
            )
            .one_or_none()
        )
        assert usage is not None, "No token-usage row was recorded for the Raw Mode query"
        assert usage.total_tokens == 19
