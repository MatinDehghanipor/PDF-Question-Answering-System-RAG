"""Tests for the human-review endpoints (Phase 4).

Covers page review (get, approve, unsatisfied), chunk editing, and
Approve All, using the full API with a real PDF and authenticated users.
"""

import io
import uuid
from pathlib import Path

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

_SUFFIX = uuid.uuid4().hex[:8]
_COUNTER = 0


def _unique(prefix: str = "t") -> str:
    global _COUNTER
    _COUNTER += 1
    return f"{prefix}{_SUFFIX}_{_COUNTER}"


def _make_real_pdf(page_count: int = 3) -> bytes:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"Test page {i + 1}", fontsize=12)
        page.insert_text((72, 100), "This is a real PDF page for review testing.", fontsize=11)
        page.insert_text((72, 120), "More text to pass quality threshold.", fontsize=11)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


async def _register_user(client, username, email, password="StrongPass1!"):
    resp = await client.post("/auth/register", json={"username": username, "email": email, "password": password})
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return resp.json()


async def _login(client, username, password="StrongPass1!"):
    resp = await client.post("/auth/login", data={"username": username, "password": password},
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _make_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_and_login(client):
    suffix = _unique()
    username = f"tu_{suffix}"
    email = f"{username}@example.com"
    user = await _register_user(client, username, email)
    token = await _login(client, username)
    return user, token


async def _upload_doc(client, token, pdf_bytes=None):
    if pdf_bytes is None:
        pdf_bytes = _make_real_pdf(3)
    resp = await client.post("/documents", files=[("files", ("test.pdf", pdf_bytes, "application/pdf"))],
                             headers=_make_header(token))
    assert resp.status_code == 201
    return resp.json()["documents"][0]


async def _get_pages(client, token, doc_id):
    resp = await client.get(f"/documents/{doc_id}/pages", headers=_make_header(token))
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture(autouse=True)
def _ensure_storage_dir():
    Path(settings.FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_page_review_returns_chunks():
    """GET /pages/{id}/review returns the page with chunks."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        pages = await _get_pages(client, token, doc["id"])
        page_id = pages[0]["id"]

        resp = await client.get(f"/pages/{page_id}/review", headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == page_id
        assert "chunks" in body
        assert len(body["chunks"]) > 0
        assert "reading_order" in body["chunks"][0]
        assert "chunk_type" in body["chunks"][0]
        assert "review_status" in body["chunks"][0]


@pytest.mark.asyncio
async def test_get_page_review_other_user_returns_404():
    """Users cannot review each other's pages."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token_a = await _create_and_login(client)
        doc = await _upload_doc(client, token_a)
        pages = await _get_pages(client, token_a, doc["id"])
        page_id = pages[0]["id"]

        _, token_b = await _create_and_login(client)
        resp = await client.get(f"/pages/{page_id}/review", headers=_make_header(token_b))
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_page_sets_status_approved():
    """POST /pages/{id}/review with decision=approved approves the page."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        pages = await _get_pages(client, token, doc["id"])
        page_id = pages[0]["id"]

        resp = await client.post(f"/pages/{page_id}/review", json={"decision": "approved"},
                                 headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision"] == "approved"
        assert body["next_status"] == "approved"

        resp2 = await client.get(f"/pages/{page_id}/review", headers=_make_header(token))
        assert resp2.json()["status"] == "approved"
@pytest.mark.asyncio
async def test_approve_all_pending_pages():
    """POST /documents/{id}/approve-all approves all awaiting-feedback pages."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)

        resp = await client.post(f"/documents/{doc['id']}/approve-all", headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["pages_approved"] == 3
        assert body["document_id"] == doc["id"]

        pages = await _get_pages(client, token, doc["id"])
        assert all(p["status"] == "approved" for p in pages)


@pytest.mark.asyncio
async def test_approve_all_no_pending_returns_zero():
    """Approve-All on a fully-approved document returns 0."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        await client.post(f"/documents/{doc['id']}/approve-all", headers=_make_header(token))
        resp = await client.post(f"/documents/{doc['id']}/approve-all", headers=_make_header(token))
        assert resp.status_code == 200
        assert resp.json()["pages_approved"] == 0
        assert "No pending pages" in resp.json()["message"]


@pytest.mark.asyncio
async def test_approve_all_other_user_returns_404():
    """User B cannot approve-all User A's document."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token_a = await _create_and_login(client)
        doc = await _upload_doc(client, token_a)
        _, token_b = await _create_and_login(client)
        resp = await client.post(f"/documents/{doc['id']}/approve-all", headers=_make_header(token_b))
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unsatisfied_round1_sets_llm_review():
    """decision=unsatisfied on Round 1 sets llm_review status."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        pages = await _get_pages(client, token, doc["id"])
        page_id = pages[0]["id"]

        resp = await client.post(f"/pages/{page_id}/review",
                                 json={"decision": "unsatisfied", "note": "Table missing"},
                                 headers=_make_header(token))
        assert resp.status_code == 200
        assert resp.json()["next_status"] == "llm_review"
        assert resp.json()["note"] == "Table missing"

        resp2 = await client.get(f"/pages/{page_id}/review", headers=_make_header(token))
        assert resp2.json()["status"] == "llm_review"


@pytest.mark.asyncio
async def test_review_non_awaiting_page_returns_409():
    """Reviewing a page not in awaiting_feedback returns 409."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        pages = await _get_pages(client, token, doc["id"])
        page_id = pages[0]["id"]

        await client.post(f"/pages/{page_id}/review", json={"decision": "approved"}, headers=_make_header(token))
        resp = await client.post(f"/pages/{page_id}/review", json={"decision": "approved"}, headers=_make_header(token))
        assert resp.status_code == 409
@pytest.mark.asyncio
async def test_edit_chunk_text():
    """PATCH /chunks/{id} with text updates the chunk and sets status=edited."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        pages = await _get_pages(client, token, doc["id"])
        first_text_chunk = next(c for c in pages[0]["chunks"] if c["chunk_type"] == "text")
        chunk_id = first_text_chunk["id"]

        resp = await client.patch(f"/pages/chunks/{chunk_id}", json={"text": "Edited text content."},
                                  headers=_make_header(token))
        assert resp.status_code == 200
        assert resp.json()["text"] == "Edited text content."
        assert resp.json()["review_status"] == "edited"


@pytest.mark.asyncio
async def test_exclude_chunk():
    """PATCH /chunks/{id} with excluded=true marks it excluded."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        pages = await _get_pages(client, token, doc["id"])
        chunk_id = pages[0]["chunks"][0]["id"]

        resp = await client.patch(f"/pages/chunks/{chunk_id}", json={"excluded": True},
                                  headers=_make_header(token))
        assert resp.status_code == 200
        assert resp.json()["excluded"] is True


@pytest.mark.asyncio
async def test_edit_chunk_after_approval_returns_409():
    """Editing a chunk on an approved page returns 409."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)
        pages = await _get_pages(client, token, doc["id"])
        chunk_id = pages[0]["chunks"][0]["id"]

        await client.post(f"/pages/{pages[0]['id']}/review", json={"decision": "approved"},
                          headers=_make_header(token))
        resp = await client.patch(f"/pages/chunks/{chunk_id}", json={"text": "new"},
                                  headers=_make_header(token))
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_document_pages():
    """GET /documents/{id}/pages lists all pages with chunks."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)

        resp = await client.get(f"/documents/{doc['id']}/pages", headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 3
        for p in body:
            assert "chunks" in p
            assert "status" in p


@pytest.mark.asyncio
async def test_document_becomes_ready_when_all_pages_approved():
    """Approve-All → document status becomes ready."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        doc = await _upload_doc(client, token)

        await client.post(f"/documents/{doc['id']}/approve-all", headers=_make_header(token))
        resp = await client.get(f"/documents/{doc['id']}", headers=_make_header(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
    yield