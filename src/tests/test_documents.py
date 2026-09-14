"""Comprehensive tests for Document management API (Phase 2).

Covers the full document lifecycle: upload, validation, listing, detail,
and deletion with a real PDF via PyMuPDF.

Each test creates a unique user so the persistent SQLite database does not
cause 409 conflicts across tests.
"""

import io
import uuid
from pathlib import Path

import fitz
import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

# Module-level unique suffix so different test files generate unique users
_SUFFIX = uuid.uuid4().hex[:8]
_COUNTER = 0


def _unique(prefix: str = "t") -> str:
    """Return a unique short string for usernames/emails."""
    global _COUNTER
    _COUNTER += 1
    return f"{prefix}{_SUFFIX}_{_COUNTER}"


@pytest.fixture(autouse=True)
def _ensure_storage_dir():
    """Ensure FILE_STORAGE_PATH exists before each test."""
    Path(settings.FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    yield


def _make_real_pdf(page_count: int = 3) -> bytes:
    """Create a tiny real PDF with multi-line text using PyMuPDF."""
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"Test page {i + 1}", fontsize=12)
        page.insert_text((72, 100), "This is a real PDF page with enough text content.", fontsize=11)
        page.insert_text((72, 120), "The quality scorer needs sufficient characters to pass threshold.", fontsize=11)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _make_fake_pdf_bytes() -> bytes:
    """Bytes starting with %%PDF- but not a valid PDF."""
    return b"%PDF-1.4\n% Fake PDF content.\n"


def _make_non_pdf_bytes() -> bytes:
    """Bytes that do NOT start with %%PDF-."""
    return b"Not a PDF file at all."


async def _register_user(client, username, email, password="StrongPass1!"):
    """Register a user via /auth/register and return user dict."""
    resp = await client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    return resp.json()


async def _login(client, username, password="StrongPass1!"):
    """Log in and return the access token."""
    resp = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _make_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_and_login(client):
    """Create a fresh user and return (user_dict, jwt_string)."""
    suffix = _unique()
    username = f"tu_{suffix}"
    email = f"{username}@example.com"
    user = await _register_user(client, username, email)
    token = await _login(client, username)
    return user, token


async def _upload_one_pdf(client, token, pdf_bytes=None, filename="test.pdf"):
    """Upload a single PDF and return the HTTP response."""
    if pdf_bytes is None:
        pdf_bytes = _make_real_pdf(3)
    upload_files = [("files", (filename, pdf_bytes, "application/pdf"))]
    return await client.post(
        "/documents", files=upload_files, headers=_make_header(token),
    )


async def _upload_many(client, token, files):
    """Upload multiple files and return the HTTP response.
    files: list of (bytes, filename) tuples."""
    upload_files = [
        ("files", (filename, content, "application/pdf"))
        for content, filename in files
    ]
    return await client.post(
        "/documents", files=upload_files, headers=_make_header(token),
    )
# ========================= POST /documents ===============================


@pytest.mark.asyncio
async def test_upload_real_pdf_success():
    """Upload a genuine 3-page PDF - creates document + pages + chunks."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user, token = await _create_and_login(client)
        resp = await _upload_one_pdf(client, token, pdf_bytes=_make_real_pdf(3))

        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        body = resp.json()
        assert len(body["documents"]) == 1
        assert body["errors"] == []

        doc = body["documents"][0]
        assert doc["filename"] == "test.pdf"
        assert doc["status"] == "awaiting_feedback"
        assert doc["page_count"] == 3
        assert doc["user_id"] == user["id"]
        assert "id" in doc
        assert "upload_date" in doc


@pytest.mark.asyncio
async def test_upload_non_pdf_extension_fails():
    """Upload with .txt extension - fails extension validation."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        resp = await _upload_one_pdf(client, token,
                                     pdf_bytes=_make_fake_pdf_bytes(),
                                     filename="report.txt")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents"] == []
        assert len(body["errors"]) == 1
        assert ".txt" in body["errors"][0]["error"]


@pytest.mark.asyncio
async def test_upload_non_pdf_magic_bytes_fails():
    """File with .pdf extension but wrong content - fails magic check."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        resp = await _upload_one_pdf(client, token,
                                     pdf_bytes=_make_non_pdf_bytes(),
                                     filename="fake.pdf")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents"] == []
        assert len(body["errors"]) == 1
@pytest.mark.asyncio
async def test_upload_empty_file_fails():
    """Upload zero-length file - fails with 'Empty file'."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        resp = await _upload_one_pdf(client, token, pdf_bytes=b"", filename="empty.pdf")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents"] == []
        assert len(body["errors"]) == 1
        assert "empty" in body["errors"][0]["error"].lower()


@pytest.mark.asyncio
async def test_upload_exceeds_max_size_fails():
    """File exceeding MAX_UPLOAD_SIZE_MB - fails size check."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)

        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        oversized = _make_real_pdf(1) + b"\x00" * max_bytes

        resp = await _upload_one_pdf(client, token, pdf_bytes=oversized,
                                     filename="huge.pdf")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents"] == []
        assert len(body["errors"]) == 1
        err_msg = body["errors"][0]["error"].lower()
        assert any(w in err_msg
                   for w in ["max upload size", str(settings.MAX_UPLOAD_SIZE_MB)])


@pytest.mark.asyncio
async def test_upload_multiple_pdfs_batch():
    """2 valid + 1 invalid - 2 succeed, 1 error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)

        resp = await _upload_many(client, token, [
            (_make_real_pdf(1), "a.pdf"),
            (_make_real_pdf(2), "b.pdf"),
            (_make_non_pdf_bytes(), "bad.pdf"),
        ])
@pytest.mark.asyncio
async def test_upload_no_files_returns_422():
    """POST /documents without files returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        resp = await client.post("/documents", headers=_make_header(token))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_without_token_returns_401():
    """POST /documents without auth returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/documents")
        assert resp.status_code == 401


# ========================= GET /documents =================================


@pytest.mark.asyncio
async def test_list_documents_empty():
    """New user sees empty document list."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        resp = await client.get("/documents", headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_documents_after_upload():
    """After uploading 2 PDFs, list shows both."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)

        await _upload_many(client, token, [
            (_make_real_pdf(1), "a.pdf"),
            (_make_real_pdf(2), "b.pdf"),
        ])

        resp = await client.get("/documents", headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert {d["filename"] for d in body["items"]} == {"a.pdf", "b.pdf"}


@pytest.mark.asyncio
async def test_list_documents_user_isolation():
    """User A's documents not visible to User B."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token_a = await _create_and_login(client)
        await _upload_one_pdf(client, token_a)

        _, token_b = await _create_and_login(client)
        resp = await client.get("/documents", headers=_make_header(token_b))
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ========================= GET /documents/{id} ============================


@pytest.mark.asyncio
async def test_get_document_detail_after_upload():
    """Document detail includes per-page statuses."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)

        resp = await _upload_one_pdf(client, token, pdf_bytes=_make_real_pdf(3))
        doc_id = resp.json()["documents"][0]["id"]

        resp = await client.get(f"/documents/{doc_id}", headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == doc_id
        assert body["filename"] == "test.pdf"
        assert body["page_count"] == 3
        assert body["status"] == "awaiting_feedback"

        pages = body["pages"]
        assert len(pages) == 3
        for p in pages:
            assert p["status"] == "awaiting_feedback"
            assert p["review_round"] == 1
            assert p["extraction_method"] in ("native", "ocr_failed"), (
                f"Expected 'native' or 'ocr_failed', got '{p['extraction_method']}'"
            )
            assert isinstance(p["quality_score"], (int, float))
            assert 0.0 <= p["quality_score"] <= 1.0


@pytest.mark.asyncio
async def test_get_document_detail_not_found():
    """GET /documents/99999 returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        resp = await client.get("/documents/99999", headers=_make_header(token))
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_document_detail_user_isolation():
    """User B cannot see User A's document detail."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token_a = await _create_and_login(client)
        resp = await _upload_one_pdf(client, token_a)
        doc_id = resp.json()["documents"][0]["id"]

        _, token_b = await _create_and_login(client)
        resp = await client.get(f"/documents/{doc_id}", headers=_make_header(token_b))
        assert resp.status_code == 404


# ========================= DELETE /documents/{id} =========================


@pytest.mark.asyncio
async def test_delete_document_success():
    """Delete returns deleted=True."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)

        resp = await _upload_one_pdf(client, token)
        doc_id = resp.json()["documents"][0]["id"]

        resp = await client.delete(f"/documents/{doc_id}",
                                   headers=_make_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is True
        assert body["document_id"] == doc_id


@pytest.mark.asyncio
async def test_delete_document_removes_file_from_disk():
    """Delete removes the PDF from disk (NFR-22)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user, token = await _create_and_login(client)

        resp = await _upload_one_pdf(client, token)
        doc_id = resp.json()["documents"][0]["id"]

        storage_path = (Path(settings.FILE_STORAGE_PATH)
                        / str(user["id"])
                        / f"{doc_id}.pdf")
        assert storage_path.exists()

        await client.delete(f"/documents/{doc_id}",
                            headers=_make_header(token))
        assert not storage_path.exists()


@pytest.mark.asyncio
async def test_delete_document_not_found():
    """DELETE /documents/99999 returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)
        resp = await client.delete("/documents/99999",
                                   headers=_make_header(token))
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_user_isolation():
    """User B cannot delete User A's document."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token_a = await _create_and_login(client)
        resp = await _upload_one_pdf(client, token_a)
        doc_id = resp.json()["documents"][0]["id"]

        _, token_b = await _create_and_login(client)
        resp = await client.delete(f"/documents/{doc_id}",
                                   headers=_make_header(token_b))
        assert resp.status_code == 404


# ========================= Edge cases =====================================


@pytest.mark.asyncio
async def test_upload_malformed_pdf_fails_processing():
    """A .pdf with PDF header but malformed body is rejected during parsing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, token = await _create_and_login(client)

        malformed = _make_fake_pdf_bytes()  # starts with %PDF- but not parseable
        resp = await _upload_one_pdf(client, token,
                                     pdf_bytes=malformed,
                                     filename="malformed.pdf")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents"] == []
        assert len(body["errors"]) == 1
        assert body["errors"][0]["filename"] == "malformed.pdf"
        assert "cannot open pdf" in body["errors"][0]["error"].lower()