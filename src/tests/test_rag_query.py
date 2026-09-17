"""Integration tests for POST /query (RAG Mode) — Phase 7.

Covers:
    - Request with no `ready` documents returns 400.
    - Request with `k` outside [1, 20] returns 422.
    - Successful RAG query returns AnswerOut with mode="rag", sources,
      and token_usage.
    - Raw Mode without `document_ids` returns 422 validation error.
    - A failed LLM call returns 502 while the Query row is still persisted.

Test doubles (see ``tests/conftest.py``):
    ``fake_embedding_model`` (autouse) replaces the embedding function in every
    module that imported it, so no model download and no Gemini API key are
    needed; the opt-in ``fake_vector_store`` fixture additionally stubs vector
    writes and retrieval with a single canned hit.  Every fake has to be
    installed both on the source module and on each module that imported the real
    function by name, because ``from x import f`` copies the reference into the
    importing module.
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

_SUFFIX = uuid.uuid4().hex[:8]

# Generous upper bound for a single-page document to finish the ingestion
# pipeline.  Kept configurable-by-constant rather than a fixed 6 s loop so a
# slow/CI machine does not produce a spurious "never reached awaiting_feedback"
# failure (a cold OCR-fallback path alone can take several seconds).
_INGESTION_TIMEOUT_SECONDS = 60.0


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _username(suffix: str) -> str:
    """Single source of truth for test usernames (also used for DB lookups)."""
    return f"rag_{suffix}"


async def _create_user_and_login(client: AsyncClient, suffix: str) -> str:
    """Register + login, return bearer token."""
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


async def _upload_and_approve_pdf(
    client: AsyncClient, headers: dict, state: dict | None = None
) -> int:
    """Upload a minimal PDF, wait for processing, approve all pages, return doc id.

    Args:
        client: In-process ASGI client.
        headers: Bearer-auth headers for the registered user.
        state: Optional dict returned by the ``fake_vector_store`` fixture defined
            in ``tests/conftest.py``.  When given, it is updated with the real
            document/page/chunk identity of the document that was just indexed, so
            the fake vector store returns metadata matching the document under
            test.

    Returns:
        The created document's id.
    """
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

    # Wait for processing to finish.  Ingestion runs off the request thread, so
    # poll with ``await asyncio.sleep`` (a blocking ``time.sleep`` would starve
    # the event loop) against a deadline rather than a fixed 6 s budget.
    deadline = time.monotonic() + _INGESTION_TIMEOUT_SECONDS
    status = None
    while time.monotonic() < deadline:
        resp = await client.get(f"/documents/{doc_id}", headers=headers)
        status = resp.json()["status"]
        if status == "awaiting_feedback":
            break
        if status == "failed":
            pytest.fail(f"Document {doc_id} failed during processing: {resp.json()}")
        await asyncio.sleep(0.3)
    else:
        pytest.fail(
            f"Document {doc_id} never reached awaiting_feedback within "
            f"{_INGESTION_TIMEOUT_SECONDS}s (last status: {status})"
        )

    # Approve all pages
    resp = await client.post(f"/documents/{doc_id}/approve-all", headers=headers)
    assert resp.status_code == 200, f"approve-all failed: {resp.status_code} {resp.text}"

    # Confirm READY
    resp = await client.get(f"/documents/{doc_id}", headers=headers)
    assert resp.json()["status"] == "ready", f"Expected ready, got {resp.json()['status']}"

    if state is not None:
        _point_fakes_at_document(state, doc_id)

    return doc_id


def _point_fakes_at_document(state: dict, doc_id: int) -> None:
    """Fill *state* with the real ids of the document that was just indexed.

    Also proves that approval actually indexed something (chunks and their
    embedding bookkeeping rows exist).  Without that check, canned fake metadata
    would let the query assertions below pass even if indexing never ran.
    """
    from app.core.database import SessionLocal
    from app.models.chunk import Chunk
    from app.models.document import Document
    from app.models.embedding import Embedding
    from app.models.page import Page

    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert doc is not None, f"Document {doc_id} not found in the database"

        page = (
            db.query(Page)
            .filter(Page.document_id == doc_id)
            .order_by(Page.page_number)
            .first()
        )
        assert page is not None, f"Document {doc_id} has no pages"

        chunk = (
            db.query(Chunk)
            .filter(Chunk.page_id == page.id)
            .order_by(Chunk.reading_order, Chunk.sub_index)
            .first()
        )
        assert chunk is not None, (
            f"Document {doc_id} has no chunks — approval did not index anything"
        )

        embedding = db.query(Embedding).filter(Embedding.chunk_id == chunk.id).first()
        assert embedding is not None, (
            f"Chunk {chunk.id} has no embedding row — indexing did not run"
        )

        state.update(
            chunk_id=f"chunk_{chunk.id}",
            document_id=doc.id,
            document_filename=doc.filename,
            page_id=page.id,
            page_number=page.page_number,
        )


def _assert_query_persisted_without_answer(username: str, text: str) -> None:
    """Assert a failed query was stored with no Answer row.

    ``POST /query`` commits the ``Query`` row before re-raising an LLM failure as
    a 502 (so usage history survives), but must not create an ``Answer`` row.
    """
    from app.core.database import SessionLocal
    from app.models.answer import Answer
    from app.models.enums import QueryMode
    from app.models.query import Query as QueryModel
    from app.models.user import User

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        assert user is not None, f"User '{username}' not found in the database"

        query = (
            db.query(QueryModel)
            .filter(QueryModel.user_id == user.id, QueryModel.text == text)
            .order_by(QueryModel.id.desc())
            .first()
        )
        assert query is not None, "The Query row was not persisted for a failed LLM call"
        assert query.mode == QueryMode.RAG
        assert query.k_value == settings.DEFAULT_TOP_K

        answers = db.query(Answer).filter(Answer.query_id == query.id).count()
        assert answers == 0, "An Answer row must not exist when the LLM call fails"


def _latest_query_k_value(username: str) -> int | None:
    """Return the ``k_value`` of the newest Query row for *username*.

    Reads the persisted row (not the HTTP response) so the test verifies what was
    actually written to the database.
    """
    from app.core.database import SessionLocal
    from app.models.query import Query as QueryModel
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
        return None if query is None else query.k_value


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
    async def test_raw_mode_without_document_ids_returns_422(self):
        """Raw Mode requires document_ids and rejects missing/empty values."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            token = await _create_user_and_login(client, _SUFFIX + "_raw_422")
            headers = {"Authorization": f"Bearer {token}"}

            resp = await client.post(
                "/query/",
                json={"text": "test", "mode": "raw"},
                headers=headers,
            )
            assert resp.status_code == 422
            assert "document_ids is required" in resp.json()["detail"]


class TestRagQueryHappyPath:
    """Successful RAG Mode query (with LLM call mocked)."""

    @pytest.mark.asyncio
    async def test_rag_query_returns_answer_with_mode_and_sources(self, fake_vector_store):
        """A query against a ready document returns AnswerOut with all expected fields."""
        state = fake_vector_store
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
                doc_id = await _upload_and_approve_pdf(client, headers, state)

                resp = await client.post(
                    "/query/",
                    json={"text": "What is AI?"},
                    headers=headers,
                )
                assert resp.status_code == 200, f"Body: {resp.text}"
                data = resp.json()

                # Shape checks
                assert data["mode"] == "rag"
                assert data["generated_text"] == (
                    "Artificial intelligence is a broad field of computer science."
                )

                # sources must name exactly the document/page that the fake search
                # reported — i.e. the real document this test uploaded.
                assert state["document_id"] == doc_id
                assert data["sources"] == [
                    {
                        "document_filename": state["document_filename"],
                        "page_number": state["page_number"],
                    }
                ]

                # source_chunk_ids must carry the real indexed chunk id.
                real_chunk_id = int(state["chunk_id"].split("_")[1])
                assert data["source_chunk_ids"] == [real_chunk_id]

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
    async def test_rag_query_with_custom_k(self, fake_vector_store):
        """Explicit k_value is accepted and recorded on the Query row."""
        state = fake_vector_store
        from app.services import llm_service

        original_call = llm_service.call_text_llm

        def _fake_llm(prompt: str, model: str):
            from app.services.llm_service import LLMCallResult
            return LLMCallResult(text="Some answer.", prompt_tokens=10, completion_tokens=5)

        llm_service.call_text_llm = _fake_llm
        suffix = _SUFFIX + "_cust_k"

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                token = await _create_user_and_login(client, suffix)
                headers = {"Authorization": f"Bearer {token}"}
                await _upload_and_approve_pdf(client, headers, state)

                resp = await client.post(
                    "/query/",
                    json={"text": "AI", "k_value": 3},
                    headers=headers,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["mode"] == "rag"
                assert data["sources"] == [
                    {
                        "document_filename": state["document_filename"],
                        "page_number": state["page_number"],
                    }
                ]

                # The override is persisted, not just used for this one request.
                assert _latest_query_k_value(_username(suffix)) == 3
        finally:
            llm_service.call_text_llm = original_call


class TestRagQueryFailurePaths:
    """Failure paths that must still leave consistent state behind (Phase 7)."""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_502(self, fake_vector_store):
        """If the LLM call fails, a 502 is returned but the Query row persists."""
        state = fake_vector_store
        from app.services import llm_service

        original_call = llm_service.call_text_llm

        def _failing_llm(prompt: str, model: str):
            raise RuntimeError("Simulated LLM failure")

        llm_service.call_text_llm = _failing_llm
        suffix = _SUFFIX + "_llm_fail"

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                token = await _create_user_and_login(client, suffix)
                headers = {"Authorization": f"Bearer {token}"}
                await _upload_and_approve_pdf(client, headers, state)

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

        # The Query row is committed *before* the 502 is raised (so usage history
        # survives), and no Answer row may be created for a failed call.
        _assert_query_persisted_without_answer(_username(suffix), "What is AI?")
