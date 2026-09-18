"""Thin wrapper around `requests` for every backend endpoint.

Centralises the base URL, JWT auth header injection, and basic error surfacing
so each Streamlit page can make API calls with a single function call and get
clean error handling without duplicating boilerplate.

Every public function:
    - Accepts the JWT token as the first argument (or `token=None` for
      unauthenticated endpoints).
    - Returns the parsed JSON on 2xx.
    - Returns `None` on a handled 401 so the caller can redirect to login.
    - Raises `ApiError` on other backend errors so the UI can display the
      backend's error message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

# Point this at the running backend (default matches uvicorn's dev default).
API_BASE: str = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")

SESSION_TIMEOUT: float = 300.0  # 5 min for long-running Raw Mode calls


# ──────────────────────────────────────────────────────────────────────
# Custom exception for surfacing backend error messages
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ApiError(Exception):
    """Wraps a non-2xx backend response with its status code and detail."""

    status_code: int
    detail: str
    error_code: str = "unknown"

    def __str__(self) -> str:
        return f"[{self.status_code}] {self.detail}"

# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _headers(token: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _handle_response(resp: requests.Response) -> Any:
    """Return parsed JSON or raise ApiError / signal 401."""
    if resp.status_code == 401:
        return None
    if not resp.ok:
        try:
            body = resp.json()
            detail = body.get("detail", str(resp.reason))
            error_code = body.get("error", "unknown")
        except Exception:
            detail = resp.text or str(resp.reason)
            error_code = "unknown"
        raise ApiError(status_code=resp.status_code, detail=detail, error_code=error_code)
    if resp.status_code == 204:
        return None
    return resp.json()


# ──────────────────────────────────────────────────────────────────────
# Auth endpoints (FR-1, FR-2)
# ──────────────────────────────────────────────────────────────────────


def register(username: str, email: str, password: str) -> dict[str, Any]:
    """POST /auth/register — create a new user account (FR-1)."""
    resp = requests.post(
        f"{API_BASE}/auth/register",
        json={"username": username, "email": email, "password": password},
        timeout=30,
    )
    return _handle_response(resp)


def login(username: str, password: str) -> dict[str, Any] | None:
    """POST /auth/login — authenticate and receive a JWT (FR-2).

    Returns the token dict on success or *None* on 401 (wrong credentials).
    """
    resp = requests.post(
        f"{API_BASE}/auth/login",
        data={"username": username, "password": password},
        timeout=30,
    )
    data = _handle_response(resp)
    if data is None:
        return None
    return data


def logout(token: str | None = None) -> dict[str, Any] | None:
    """POST /auth/logout — tell the backend the client is discarding its JWT (FR-2).

    Logout is stateless on the backend (no token blacklist — see
    ``app/api/routes/auth.py``), so the *real* invalidation is the UI dropping
    the token from ``st.session_state``.  This call is therefore best-effort:
    an already-expired token yields a 401, which :func:`_handle_response`
    turns into *None* rather than an error.
    """
    resp = requests.post(
        f"{API_BASE}/auth/logout",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


# ──────────────────────────────────────────────────────────────────────
# Health check (used by the entry page to detect an unreachable backend)
# ──────────────────────────────────────────────────────────────────────


def health() -> dict[str, Any]:
    """GET /health — liveness probe (no auth required).

    Used by ``streamlit_app.py`` to show a clear "cannot reach the server"
    banner before the user types credentials into a dead form.  Short timeout
    (5 s) so a down backend fails fast instead of hanging the page.
    """
    resp = requests.get(f"{API_BASE}/health", timeout=5)
    return _handle_response(resp)


# ──────────────────────────────────────────────────────────────────────
# Config (GET-only limits endpoint for UI consumption)
# ──────────────────────────────────────────────────────────────────────


def get_limits(token: str | None = None) -> dict[str, Any]:
    """GET /config/limits — read-only backend limits for the UI."""
    resp = requests.get(
        f"{API_BASE}/config/limits",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


# ──────────────────────────────────────────────────────────────────────
# Document endpoints (FR-4, FR-5, FR-22, FR-23, FR-13, NFR-26)
# ──────────────────────────────────────────────────────────────────────


def upload_documents_bytes(token: str, files_data: list[tuple[str, bytes]]) -> dict[str, Any]:
    """POST /documents — upload PDFs given (filename, bytes) pairs (FR-4, FR-5)."""
    files = [("files", (name, content, "application/pdf")) for name, content in files_data]
    resp = requests.post(
        f"{API_BASE}/documents",
        files=files,
        headers=_headers(token),
        timeout=120,
    )
    return _handle_response(resp)


def list_documents(token: str) -> dict[str, Any]:
    """GET /documents — list all documents for the current user (FR-22)."""
    resp = requests.get(
        f"{API_BASE}/documents",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def get_document_detail(token: str, doc_id: int) -> dict[str, Any]:
    """GET /documents/{id} — full document detail with per-page statuses."""
    resp = requests.get(
        f"{API_BASE}/documents/{doc_id}",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def delete_document(token: str, doc_id: int) -> dict[str, Any] | None:
    """DELETE /documents/{id} — delete a document and all its data (FR-23)."""
    resp = requests.delete(
        f"{API_BASE}/documents/{doc_id}",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def get_document_pages(token: str, doc_id: int) -> list[dict[str, Any]]:
    """GET /documents/{id}/pages — list pages with chunks for review (NFR-16)."""
    resp = requests.get(
        f"{API_BASE}/documents/{doc_id}/pages",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def approve_all(token: str, doc_id: int) -> dict[str, Any]:
    """POST /documents/{id}/approve-all — approve all pending pages (FR-13)."""
    resp = requests.post(
        f"{API_BASE}/documents/{doc_id}/approve-all",
        headers=_headers(token),
        timeout=60,
    )
    return _handle_response(resp)

# ──────────────────────────────────────────────────────────────────────
# Page review endpoints (FR-11, FR-12, NFR-19, NFR-27)
# ──────────────────────────────────────────────────────────────────────


def get_page_review(token: str, page_id: int) -> dict[str, Any]:
    """GET /pages/{id}/review — fetch page with chunks for human review."""
    resp = requests.get(
        f"{API_BASE}/pages/{page_id}/review",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def submit_page_review(
    token: str,
    page_id: int,
    decision: str,
    note: str | None = None,
) -> dict[str, Any]:
    """POST /pages/{id}/review — approve or mark unsatisfied (FR-11)."""
    resp = requests.post(
        f"{API_BASE}/pages/{page_id}/review",
        json={"decision": decision, "note": note},
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def patch_chunk(token: str, chunk_id: int, **kwargs: Any) -> dict[str, Any]:
    """PATCH /pages/chunks/{id} — edit chunk text or mark excluded (FR-12).

    NOTE: the route lives under the page router's ``/pages`` prefix
    (``app/api/routes/pages.py`` → ``APIRouter(prefix="/pages")``), so the
    real path is ``/pages/chunks/{id}``, not ``/chunks/{id}``.  Verified
    against ``src/tests/test_review.py::test_edit_chunk_text``.
    """
    body: dict[str, Any] = {}
    if "text" in kwargs:
        body["text"] = kwargs["text"]
    if "excluded" in kwargs:
        body["excluded"] = kwargs["excluded"]
    resp = requests.patch(
        f"{API_BASE}/pages/chunks/{chunk_id}",
        json=body,
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


# ──────────────────────────────────────────────────────────────────────
# Query endpoints (FR-24, FR-26, FR-29, FR-30, FR-33)
# ──────────────────────────────────────────────────────────────────────


def submit_query(
    token: str,
    text: str,
    mode: str = "rag",
    k_value: int | None = None,
    document_ids: list[int] | None = None,
) -> dict[str, Any]:
    """POST /query — ask a question in RAG or Raw mode (FR-24/26)."""
    body: dict[str, Any] = {"text": text, "mode": mode}
    if k_value is not None:
        body["k_value"] = k_value
    if document_ids is not None:
        body["document_ids"] = document_ids
    resp = requests.post(
        f"{API_BASE}/query",
        json=body,
        headers=_headers(token),
        timeout=SESSION_TIMEOUT,
    )
    return _handle_response(resp)


# ──────────────────────────────────────────────────────────────────────
# Feedback endpoints (FR-31, FR-32)
# ──────────────────────────────────────────────────────────────────────


def submit_feedback(
    token: str,
    answer_id: int,
    rating: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """POST /feedback — rate an answer with optional comment (FR-31/32)."""
    body: dict[str, Any] = {"answer_id": answer_id}
    if rating is not None:
        body["rating"] = rating
    if comment is not None:
        body["comment"] = comment
    resp = requests.post(
        f"{API_BASE}/feedback",
        json=body,
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


# ──────────────────────────────────────────────────────────────────────
# Usage / token statistics endpoints (FR-34, FR-35)
# ──────────────────────────────────────────────────────────────────────


def get_usage_summary(
    token: str,
    group_by: str | None = None,
    document_id: int | None = None,
) -> dict[str, Any]:
    """GET /usage/summary — aggregate token usage (FR-34)."""
    params: dict[str, Any] = {}
    if group_by:
        params["group_by"] = group_by
    if document_id:
        params["document_id"] = document_id
    resp = requests.get(
        f"{API_BASE}/usage/summary",
        params=params,
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def list_usage(token: str, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    """GET /usage — list individual token usage records (FR-35)."""
    resp = requests.get(
        f"{API_BASE}/usage",
        params={"skip": skip, "limit": limit},
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def get_query_usage(token: str, query_id: int) -> list[dict[str, Any]]:
    """GET /usage/queries/{id} — token usage for a single query (FR-33, NFR-30).

    Lets the Usage page drill into one query's LLM cost.  A query id that does
    not exist or belongs to another user yields a 404 ``ApiError`` (per-user
    isolation, FR-3 / NFR-21).
    """
    resp = requests.get(
        f"{API_BASE}/usage/queries/{query_id}",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)


def get_page_usage(token: str, page_id: int) -> list[dict[str, Any]]:
    """GET /usage/pages/{id} — token usage for a page's LLM Review call (FR-15, FR-33).

    Covers the "per page" half of NFR-30 (the LLM Review calls made during
    ingestion), complementing the per-query view above.
    """
    resp = requests.get(
        f"{API_BASE}/usage/pages/{page_id}",
        headers=_headers(token),
        timeout=30,
    )
    return _handle_response(resp)
