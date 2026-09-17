"""Integration tests for POST /feedback — Phase 9.

Covers (FR-31, FR-32, NFR-28; UC9):
    - rating only, comment only, and both together all succeed
    - neither a rating nor a non-empty comment → 400
    - another user's answer → 404 (and a non-existent answer_id → 404)
    - a rating outside the enum → 422
    - multiple submissions per answer are allowed
    - RAG Mode: joining Feedback -> Answer -> Query reconstructs the mode and
      the exact chunks that feedback implicitly judges
    - Raw Mode: feedback works even though ``source_chunk_ids`` is NULL there
    - feedback stays optional, so it can never block further querying

Test doubles: the autouse ``fake_embedding_model`` fixture keeps the embedding
model out of every test, and the opt-in ``fake_vector_store`` fixture stubs
vector writes/retrieval with one canned hit.  Both the raw and RAG LLM calls
are stubbed per test, so no API key is required.
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

_SUFFIX = uuid.uuid4().hex[:8]

# Generous bound for a single-page document to finish ingestion (the same
# rationale as test_rag_query.py: a cold OCR-fallback path can take seconds on
# a slow machine, so poll to a deadline instead of assuming a fixed budget).
_INGESTION_TIMEOUT_SECONDS = 60.0


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _username(suffix: str) -> str:
    """Single source of truth for test usernames (also used for DB lookups)."""
    return f"fb_{suffix}"


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


def _make_pdf_bytes() -> bytes:
    """Build a minimal but real one-page PDF."""
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page.insert_text((72, 72), "Feedback test content about artificial intelligence.", fontsize=12)
    pdf_bytes = io.BytesIO()
    pdf_doc.save(pdf_bytes)
    pdf_doc.close()
    return pdf_bytes.getvalue()


async def _upload_pdf(client: AsyncClient, headers: dict, filename: str) -> int:
    """Upload a one-page PDF, return the created document id."""
    resp = await client.post(
        "/documents",
        files=[("files", (filename, _make_pdf_bytes(), "application/pdf"))],
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["documents"][0]["id"]


async def _wait_for_awaiting_feedback(client: AsyncClient, headers: dict, doc_id: int) -> None:
    """Poll until the document's ingestion pipeline finishes."""
    deadline = time.monotonic() + _INGESTION_TIMEOUT_SECONDS
    status = None
    while time.monotonic() < deadline:
        resp = await client.get(f"/documents/{doc_id}", headers=headers)
        status = resp.json()["status"]
        if status == "awaiting_feedback":
            return
        if status == "failed":
            pytest.fail(f"Document {doc_id} failed during processing: {resp.json()}")
        await asyncio.sleep(0.3)
    pytest.fail(
        f"Document {doc_id} never reached awaiting_feedback within "
        f"{_INGESTION_TIMEOUT_SECONDS}s (last status: {status})"
    )


async def _make_rag_answer(client: AsyncClient, headers: dict, state: dict) -> dict:
    """Produce a RAG Mode answer and return ``{answer_id, query_id}``.

    Approves the document so chunks really exist and are indexed, then issues a
    RAG query with the LLM call stubbed.  Chunk identity is read back from the
    database so the test can assert on the exact chunks later.
    """
    from app.services import llm_service

    doc_id = await _upload_pdf(client, headers, "feedback_rag.pdf")
    await _wait_for_awaiting_feedback(client, headers, doc_id)

    resp = await client.post(f"/documents/{doc_id}/approve-all", headers=headers)
    assert resp.status_code == 200, resp.text

    _point_fakes_at_document(state, doc_id)

    def _fake_llm(prompt: str, model: str):
        from app.services.llm_service import LLMCallResult
        return LLMCallResult(text="A RAG answer.", prompt_tokens=11, completion_tokens=5)

    original_call = llm_service.call_text_llm
    llm_service.call_text_llm = _fake_llm
    try:
        resp = await client.post(
            "/query/",
            json={"text": "What is artificial intelligence?"},
            headers=headers,
        )
    finally:
        llm_service.call_text_llm = original_call

    assert resp.status_code == 200, resp.text
    data = resp.json()
    state["chunk_ids"] = data["source_chunk_ids"]
    return {"answer_id": data["id"], "query_id": data["query_id"], "document_id": doc_id}


async def _make_raw_answer(client: AsyncClient, headers: dict) -> dict:
    """Produce a Raw Mode answer and return ``{answer_id, query_id}``.

    Raw Mode needs no ``ready`` document, so ingestion does not have to finish.
    """
    from app.services import llm_service

    doc_id = await _upload_pdf(client, headers, "feedback_raw.pdf")

    def _fake_llm_with_files(prompt: str, file_paths: list[str], model: str):
        from app.services.llm_service import LLMCallResult
        return LLMCallResult(text="A raw answer.", prompt_tokens=3, completion_tokens=2)

    original_call = llm_service.call_text_llm_with_files
    llm_service.call_text_llm_with_files = _fake_llm_with_files
    try:
        resp = await client.post(
            "/query/",
            json={"text": "Summarize this file.", "mode": "raw", "document_ids": [doc_id]},
            headers=headers,
        )
    finally:
        llm_service.call_text_llm_with_files = original_call

    assert resp.status_code == 200, resp.text
    data = resp.json()
    return {"answer_id": data["id"], "query_id": data["query_id"], "document_id": doc_id}


def _point_fakes_at_document(state: dict, doc_id: int) -> None:
    """Fill *state* with the real ids of the document that was just indexed.

    Mirrors test_rag_query.py: proves approval actually indexed something, and
    gives the canned fake vector-store hit metadata that matches the document
    under test.
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
        assert chunk is not None, f"Document {doc_id} has no chunks — approval did not index"

        embedding = db.query(Embedding).filter(Embedding.chunk_id == chunk.id).first()
        assert embedding is not None, f"Chunk {chunk.id} has no embedding row — indexing did not run"

        state.update(
            chunk_id=f"chunk_{chunk.id}",
            document_id=doc.id,
            document_filename=doc.filename,
            page_id=page.id,
            page_number=page.page_number,
        )


def _load_feedback_join(feedback_id: int) -> dict:
    """Re-read one feedback row and reconstruct FR-32's linkage by joining.

    This is the DoD's explicit join requirement: ``Feedback -> Answer -> Query``
    plus ``Answer.source_chunk_ids`` must be enough to recover the query, the
    answer, the mode used, and the exact chunks that were used (hence which
    chunks this feedback implicitly judges).  Reading it back from the database
    rather than trusting the HTTP response proves what was actually persisted.
    """
    from app.core.database import SessionLocal
    from app.models.answer import Answer
    from app.models.feedback import Feedback
    from app.models.query import Query as QueryModel

    with SessionLocal() as db:
        row = (
            db.query(Feedback, QueryModel.mode, Answer.source_chunk_ids)
            .join(QueryModel, Feedback.query_id == QueryModel.id)
            .join(Answer, Feedback.answer_id == Answer.id)
            .filter(Feedback.id == feedback_id)
            .one_or_none()
        )
        assert row is not None, f"Feedback {feedback_id} not found in the database"
        feedback, mode, chunk_ids = row
        return {
            "id": feedback.id,
            "query_id": feedback.query_id,
            "answer_id": feedback.answer_id,
            "rating": feedback.rating.value if feedback.rating is not None else None,
            "comment": feedback.comment,
            "mode": mode.value if hasattr(mode, "value") else mode,
            "chunk_ids": chunk_ids,
        }


def _count_feedback_for_answer(answer_id: int) -> int:
    """Count persisted feedback rows for one answer."""
    from app.core.database import SessionLocal
    from app.models.feedback import Feedback

    with SessionLocal() as db:
        return db.query(Feedback).filter(Feedback.answer_id == answer_id).count()


async def _login(client: AsyncClient, suffix: str) -> dict:
    """Register + login, returning ready-to-use bearer headers."""
    token = await _create_user_and_login(client, suffix)
    return {"Authorization": f"Bearer {token}"}


async def _ask_rag(client: AsyncClient, headers: dict, text: str) -> int:
    """Issue one more RAG query with the answering LLM stubbed; return answer id.

    Used to show the system keeps answering while no feedback has been left
    (NFR-28), reusing the document that a previous ``_make_rag_answer`` call
    already approved and pointed the fake vector store at.
    """
    from app.services import llm_service

    def _fake_llm(prompt: str, model: str):
        from app.services.llm_service import LLMCallResult
        return LLMCallResult(text="Another RAG answer.", prompt_tokens=7, completion_tokens=3)

    original_call = llm_service.call_text_llm
    llm_service.call_text_llm = _fake_llm
    try:
        resp = await client.post("/query/", json={"text": text}, headers=headers)
    finally:
        llm_service.call_text_llm = original_call

    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# The only module allowed to import the ``Feedback`` ORM model.  Kept as a
# constant so the NFR-28 guard below reads as an explicit allow-list rather than
# a bare string, and so a future *non-gating* consumer has an obvious place to
# register itself (with a reason) after being checked for a gate.
_ALLOWED_FEEDBACK_IMPORTERS = {"services/feedback_service.py"}


def _files_importing_the_feedback_model() -> set[str]:
    """Return app-relative paths of route/service modules importing ``Feedback``.

    Parses the files with :mod:`ast` instead of grepping text, because several
    modules legitimately *mention* Feedback in comments (the standing per-user
    isolation rule repeats the table name); only a real import could ever be used
    to read a feedback row as a precondition.

    Returns:
        App-relative POSIX-style paths, e.g. ``{"services/feedback_service.py"}``.
    """
    import ast
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    found: set[str] = set()
    for sub in ("api/routes", "services"):
        for path in sorted((app_dir / sub).glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names = {alias.name for alias in node.names}
                    if node.module == "app.models.feedback" and "Feedback" in names:
                        found.add(path.relative_to(app_dir).as_posix())
                elif isinstance(node, ast.Import):
                    if any(
                        alias.name == "app.models.feedback" for alias in node.names
                    ):
                        found.add(path.relative_to(app_dir).as_posix())
    return found


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestFeedbackValidation:
    """The 'at least one signal' rule and rating validation (FR-31)."""

    @pytest.mark.asyncio
    async def test_rating_only_succeeds(self):
        """A rating with no comment is a complete submission."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_rating_only")
            ans = await _make_raw_answer(client, headers)

            resp = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "rating": "positive"},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

            data = resp.json()
            assert data["rating"] == "positive"
            assert data["comment"] is None
            assert data["answer_id"] == ans["answer_id"]
            assert data["query_id"] == ans["query_id"]
            assert data["timestamp"], "a server-side timestamp must be returned"

    @pytest.mark.asyncio
    async def test_comment_only_succeeds(self):
        """A comment with no rating is a complete submission."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_comment_only")
            ans = await _make_raw_answer(client, headers)

            resp = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "comment": "Answer was too vague."},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

            data = resp.json()
            assert data["rating"] is None
            assert data["comment"] == "Answer was too vague."

            row = _load_feedback_join(data["id"])
            assert row["rating"] is None
            assert row["comment"] == "Answer was too vague."

    @pytest.mark.asyncio
    async def test_neither_rating_nor_comment_returns_400(self):
        """With no rating and no comment there is nothing to record."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_neither")
            ans = await _make_raw_answer(client, headers)

            resp = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"]},
                headers=headers,
            )
            assert resp.status_code == 400, resp.text
            assert "rating and/or" in resp.json()["detail"]
            assert _count_feedback_for_answer(ans["answer_id"]) == 0

    @pytest.mark.asyncio
    async def test_blank_comment_without_rating_returns_400(self):
        """``comment=""``/whitespace means absent, so it cannot stand alone."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_blank")
            ans = await _make_raw_answer(client, headers)

            for blank in ("", "   ", "\n\t"):
                resp = await client.post(
                    "/feedback",
                    json={"answer_id": ans["answer_id"], "comment": blank},
                    headers=headers,
                )
                assert resp.status_code == 400, f"comment={blank!r} -> {resp.status_code}"

            assert _count_feedback_for_answer(ans["answer_id"]) == 0

    @pytest.mark.asyncio
    async def test_empty_comment_with_rating_succeeds(self):
        """``comment=""`` alongside a rating is fine — the rating is the signal."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_empty_with_rating")
            ans = await _make_raw_answer(client, headers)

            resp = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "rating": "positive", "comment": ""},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text
            data = resp.json()
            assert data["rating"] == "positive"
            # Normalised to NULL rather than stored as empty text.
            assert data["comment"] is None

    @pytest.mark.asyncio
    async def test_rating_outside_enum_returns_422(self):
        """An arbitrary rating string is rejected by validation, not stored."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_bad_rating")
            ans = await _make_raw_answer(client, headers)

            for bad in ("maybe", "POSITIVE", "5", "up"):
                resp = await client.post(
                    "/feedback",
                    json={"answer_id": ans["answer_id"], "rating": bad},
                    headers=headers,
                )
                assert resp.status_code == 422, f"rating={bad!r} -> {resp.status_code}"

            assert _count_feedback_for_answer(ans["answer_id"]) == 0


class TestFeedbackOwnership:
    """Feedback can only be left on the caller's own answers (FR-3 / NFR-21)."""

    @pytest.mark.asyncio
    async def test_another_users_answer_returns_404(self):
        """User B cannot rate user A's answer, and learns nothing about it."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers_a = await _login(client, _SUFFIX + "_owner")
            ans_a = await _make_raw_answer(client, headers_a)

            headers_b = await _login(client, _SUFFIX + "_intruder")
            resp = await client.post(
                "/feedback",
                json={"answer_id": ans_a["answer_id"], "rating": "positive"},
                headers=headers_b,
            )
            assert resp.status_code == 404, resp.text
            assert _count_feedback_for_answer(ans_a["answer_id"]) == 0

            # Owner can still leave their own feedback afterwards.
            resp = await client.post(
                "/feedback",
                json={"answer_id": ans_a["answer_id"], "rating": "positive"},
                headers=headers_a,
            )
            assert resp.status_code == 201, resp.text

    @pytest.mark.asyncio
    async def test_nonexistent_answer_returns_404(self):
        """An unknown answer_id is a 404, identical to the not-yours case."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_ghost")

            resp = await client.post(
                "/feedback",
                json={"answer_id": 999_999_999, "rating": "positive"},
                headers=headers,
            )
            assert resp.status_code == 404, resp.text
            # The detail text is deliberately not asserted: ``app.main``'s global
            # HTTP-exception handler rewrites the detail of *every* 404 to
            # "Route '<path>' not found.", so it reads the same whether the path
            # itself is unknown or this endpoint rejected the request.  Asserting
            # the status plus the standard JSON error shape is what the existing
            # 404 tests do, and the meaningful claim — that nothing was written —
            # is verified against the database instead.
            assert resp.json()["error"] == "not_found"
            assert _count_feedback_for_answer(999_999_999) == 0

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        """Feedback requires authentication (NFR-20)."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_noauth")
            ans = await _make_raw_answer(client, headers)

            resp = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "rating": "positive"},
            )
            assert resp.status_code == 401, resp.text
            assert _count_feedback_for_answer(ans["answer_id"]) == 0


class TestFeedbackPersistenceLinks:
    """FR-32: feedback is persisted and linked to query/answer/mode/chunks."""

    @pytest.mark.asyncio
    async def test_rag_mode_feedback_reconstructs_mode_and_chunks(self, fake_vector_store):
        """The Feedback -> Answer -> Query join recovers mode and chunks used."""
        state = fake_vector_store
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_rag_join")
            ans = await _make_rag_answer(client, headers, state)

            resp = await client.post(
                "/feedback",
                json={
                    "answer_id": ans["answer_id"],
                    "rating": "negative",
                    "comment": "The retrieved excerpt was off-topic.",
                },
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

            row = _load_feedback_join(resp.json()["id"])
            assert row["query_id"] == ans["query_id"]
            assert row["answer_id"] == ans["answer_id"]
            # Mode used, recovered via Query — not duplicated onto Feedback.
            assert row["mode"] == "rag"
            # Chunks used, recovered via Answer.source_chunk_ids.
            expected_chunk_id = int(state["chunk_id"].split("_")[1])
            assert row["chunk_ids"] == [expected_chunk_id]
            assert row["chunk_ids"] == state["chunk_ids"]

            # Those judged chunks must be real rows, so the feedback is traceable
            # back to actual content rather than a stale/dangling id.
            from app.core.database import SessionLocal
            from app.models.chunk import Chunk

            with SessionLocal() as db:
                for chunk_id in row["chunk_ids"]:
                    assert db.get(Chunk, chunk_id) is not None, (
                        f"chunk {chunk_id} referenced by feedback does not exist"
                    )

    @pytest.mark.asyncio
    async def test_raw_mode_feedback_tolerates_null_chunk_ids(self):
        """Raw Mode has no chunks, so the same join must survive a NULL list."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_raw_join")
            ans = await _make_raw_answer(client, headers)

            resp = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "rating": "positive"},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

            row = _load_feedback_join(resp.json()["id"])
            assert row["query_id"] == ans["query_id"]
            assert row["mode"] == "raw"
            assert row["chunk_ids"] is None, "Raw Mode must store no chunk linkage"

    @pytest.mark.asyncio
    async def test_comment_only_rag_feedback_keeps_chunk_link(self, fake_vector_store):
        """A comment-only submission links to chunks just like a rated one."""
        state = fake_vector_store
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_rag_comment")
            ans = await _make_rag_answer(client, headers, state)

            resp = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "comment": "Chunk boundary cut a sentence."},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

            row = _load_feedback_join(resp.json()["id"])
            assert row["rating"] is None
            assert row["mode"] == "rag"
            assert row["chunk_ids"] == state["chunk_ids"]

    @pytest.mark.asyncio
    async def test_multiple_submissions_are_all_stored(self):
        """Changing your mind adds a row; nothing is overwritten or blocked."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_repeat")
            ans = await _make_raw_answer(client, headers)

            first = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "rating": "positive"},
                headers=headers,
            )
            second = await client.post(
                "/feedback",
                json={"answer_id": ans["answer_id"], "rating": "negative", "comment": "On reflection, no."},
                headers=headers,
            )
            assert first.status_code == 201, first.text
            assert second.status_code == 201, second.text

            first_id = first.json()["id"]
            second_id = second.json()["id"]
            assert first_id != second_id, "each submission must be its own row"
            assert second_id > first_id
            assert _count_feedback_for_answer(ans["answer_id"]) == 2

            # Both rows are preserved verbatim, so a later reader can choose the
            # most recent row or the full history without data having been lost.
            assert _load_feedback_join(first_id)["rating"] == "positive"
            latest = _load_feedback_join(second_id)
            assert latest["rating"] == "negative"
            assert latest["comment"] == "On reflection, no."


class TestFeedbackIsOptional:
    """NFR-28 — feedback is optional and must never gate further use.

    The phase instructions call for *confirming* (not re-implementing) that
    nothing requires feedback before the user can continue.  One behavioural
    test walks the real user path; one static test pins the invariant in the
    code so a later phase cannot quietly introduce a gate.
    """

    @pytest.mark.asyncio
    async def test_system_stays_usable_without_any_feedback(self, fake_vector_store):
        """A user who never leaves feedback can keep querying in both modes."""
        state = fake_vector_store
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_optional")

            answered = await _make_rag_answer(client, headers, state)
            assert _count_feedback_for_answer(answered["answer_id"]) == 0, (
                "no feedback should exist until the user explicitly submits it"
            )

            # Keep using the system while feedback is still absent: another RAG
            # query against the same ready document must be answered normally.
            second_answer_id = await _ask_rag(client, headers, "And what is ML?")
            assert second_answer_id != answered["answer_id"]
            assert _count_feedback_for_answer(second_answer_id) == 0

            # Raw Mode stays available too, still with zero feedback anywhere.
            raw = await _make_raw_answer(client, headers)
            assert _count_feedback_for_answer(raw["answer_id"]) == 0

    def test_no_other_route_or_service_reads_feedback_as_a_gate(self):
        """Nothing outside the feedback write path even loads the Feedback model.

        A gate would have to import the model to inspect a row, so restricting
        the importer set is a direct, low-false-positive check on NFR-28.  This
        is a guard against future work, not a description of today's code: if a
        new module appears here, verify it does not require feedback before
        letting the user continue, then register it in
        ``_ALLOWED_FEEDBACK_IMPORTERS`` with its reason.
        """
        assert _files_importing_the_feedback_model() == _ALLOWED_FEEDBACK_IMPORTERS, (
            "Only the feedback write path may import the Feedback ORM model. "
            "A new importer must be checked for an NFR-28 gate (nothing may "
            "require feedback before continuing); if it is genuinely "
            "non-gating, extend _ALLOWED_FEEDBACK_IMPORTERS and say why."
        )

    @staticmethod
    def _stub_raw_llm(monkeypatch: pytest.MonkeyPatch) -> None:
        """Make Raw Mode answerable without an API key."""
        from app.services import llm_service
        from app.services.llm_service import LLMCallResult

        monkeypatch.setattr(
            llm_service,
            "call_text_llm_with_files",
            lambda prompt, file_paths, model: LLMCallResult(
                text="A raw answer.", prompt_tokens=3, completion_tokens=2
            ),
        )

    @pytest.mark.asyncio
    async def test_raw_mode_answer_can_be_followed_up_without_feedback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Raw Mode answer can be queried again with zero feedback recorded."""
        self._stub_raw_llm(monkeypatch)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_opt_raw")
            first = await _make_raw_answer(client, headers)

            # Nothing was submitted for the first answer — the state most likely
            # to reveal an accidental "must rate before continuing" gate.
            assert _count_feedback_for_answer(first["answer_id"]) == 0

            follow_up = await client.post(
                "/query/",
                json={
                    "text": "And what about the second part?",
                    "mode": "raw",
                    "document_ids": [first["document_id"]],
                },
                headers=headers,
            )
            assert follow_up.status_code == 200, follow_up.text

            # Leaving feedback afterwards must not change that either.
            resp = await client.post(
                "/feedback",
                json={"answer_id": first["answer_id"], "rating": "positive"},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

            after_feedback = await client.post(
                "/query/",
                json={
                    "text": "One more question.",
                    "mode": "raw",
                    "document_ids": [first["document_id"]],
                },
                headers=headers,
            )
            assert after_feedback.status_code == 200, after_feedback.text

    @pytest.mark.asyncio
    async def test_rag_mode_answer_can_be_followed_up_without_feedback(
        self, fake_vector_store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RAG Mode — the path with the most preconditions — ignores feedback too."""
        from app.services import llm_service
        from app.services.llm_service import LLMCallResult

        monkeypatch.setattr(
            llm_service,
            "call_text_llm",
            lambda prompt, model: LLMCallResult(
                text="A RAG answer.", prompt_tokens=11, completion_tokens=5
            ),
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = await _login(client, _SUFFIX + "_opt_rag")
            first = await _make_rag_answer(client, headers, fake_vector_store)
            assert _count_feedback_for_answer(first["answer_id"]) == 0

            # The document is ``ready`` and feedback exists for nobody, yet a
            # second query must still go through on its own merits (UC4's
            # precondition is document readiness, never feedback).
            follow_up = await client.post(
                "/query/",
                json={"text": "What else does it say?"},
                headers=headers,
            )
            assert follow_up.status_code == 200, follow_up.text

            resp = await client.post(
                "/feedback",
                json={"answer_id": first["answer_id"], "comment": "Good answer."},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

            after_feedback = await client.post(
                "/query/",
                json={"text": "And one more?"},
                headers=headers,
            )
            assert after_feedback.status_code == 200, after_feedback.text

