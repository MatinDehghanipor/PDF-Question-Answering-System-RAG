"""Shared helpers for the Phase 12 Streamlit client.

Why this module exists
----------------------
All four pages need the same handful of things: the JWT guard, one place that
turns backend/transport failures into friendly UI messages, the status
vocabulary required by NFR-16 / NFR-19 / NFR-24, the backend limits from
``GET /config/limits``, and the shared sidebar.  Keeping them here means
``1_Documents.py`` … ``4_Usage.py`` stay focused on layout and the required
visual cues cannot drift between screens.

Import order matters
--------------------
This module puts ``frontend/`` on ``sys.path`` *before* importing
:mod:`api_client`.  Each page still performs the same two-line ``sys.path`` fix
first, because ``import ui_helpers`` itself cannot succeed until ``frontend/``
is importable — pages can be opened directly by URL without the entry point
having run, so the fix cannot live only in ``streamlit_app.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, TypeVar

import requests
import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parent
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

import api_client as api  # noqa: E402  (must follow the sys.path fix above)

T = TypeVar("T")

# ──────────────────────────────────────────────────────────────────────
# Page paths, exactly as Streamlit's multipage API expects them
# (relative to the entry point ``streamlit_app.py``).
# ──────────────────────────────────────────────────────────────────────

LOGIN_PAGE = "streamlit_app.py"
DOCUMENTS_PAGE = "pages/1_Documents.py"
REVIEW_PAGE = "pages/2_Review.py"
QUERY_PAGE = "pages/3_Query.py"
USAGE_PAGE = "pages/4_Usage.py"

# ──────────────────────────────────────────────────────────────────────
# Status vocabulary (NFR-16 page/document status, NFR-19 round + quality,
# NFR-24 LLM-Review flag).  Values mirror app/models/enums.py.
# ──────────────────────────────────────────────────────────────────────

PAGE_STATUS_LABELS: dict[str, str] = {
    "initial_processing": "⏳ Initial Processing",
    "awaiting_feedback": "📝 Awaiting Feedback",
    "llm_review": "🤖 LLM Review",
    "approved": "✅ Approved",
    "discarded": "🗑️ Discarded",
}

DOCUMENT_STATUS_LABELS: dict[str, str] = {
    "uploaded": "⬆️ Uploaded",
    "processing": "⏳ Processing",
    "awaiting_feedback": "📝 Awaiting Feedback",
    "ready": "✅ Ready",
    "discarded": "🗑️ Discarded",
    "failed": "❌ Failed",
}

EXTRACTION_METHOD_LABELS: dict[str, str] = {
    "native": "Native extraction (PyMuPDF)",
    "ocr": "OCR (Tesseract)",
    "llm_vision": "LLM Review (vision model)",
    "ocr_failed": "OCR failed — no content extracted",
    "llm_review_failed": "LLM Review failed — retry by marking unsatisfied again",
}

CHUNK_TYPE_LABELS: dict[str, str] = {
    "text": "📄 text",
    "table": "📊 table",
    "image": "🖼️ image",
}

CHUNK_REVIEW_STATUS_LABELS: dict[str, str] = {
    "pending": "pending review",
    "approved": "approved",
    "edited": "edited by you",
    "rejected": "excluded / rejected",
}

# Fallbacks used only if GET /config/limits is unreachable (same OD-2/OD-7
# defaults as app/core/config.py) so the UI degrades instead of breaking.
_LIMIT_FALLBACKS: dict[str, int] = {
    "MIN_TOP_K": 1,
    "MAX_TOP_K": 20,
    "DEFAULT_TOP_K": 5,
    "MAX_UPLOAD_SIZE_MB": 100,
    "RAW_MODE_MAX_FILE_MB": 50,
    "RAW_MODE_MAX_PAGES": 100,
}


# ──────────────────────────────────────────────────────────────────────
# Display helpers — one source of truth for the NFR visual cues
# ──────────────────────────────────────────────────────────────────────


def status_badge(status: str | None, kind: str = "page") -> str:
    """Return the display badge for a page or document status (NFR-16).

    Args:
        status: Raw enum value from the API (e.g. ``awaiting_feedback``).
        kind: ``"page"`` or ``"document"`` — which label map to use.

    Returns:
        A short emoji + text badge; unknown values are passed through verbatim
        so a future backend status is still visible rather than swallowed.
    """
    labels = PAGE_STATUS_LABELS if kind == "page" else DOCUMENT_STATUS_LABELS
    if status is None:
        return "—"
    return labels.get(status, status)


def round_label(page: dict[str, Any]) -> str:
    """Describe which review round produced the displayed content (NFR-19).

    Round 1 comes from native extraction or OCR; Round 2 always comes from the
    LLM Review escalation (FR-14).  ``review_round`` is 1 or 2 in the API.
    """
    rnd = page.get("review_round") or 1
    if rnd >= 2:
        return "Round 2 — content produced by LLM Review"
    method = page.get("extraction_method")
    if method == "ocr":
        return "Round 1 — content produced by OCR"
    if method == "llm_vision":
        return "Round 1 — content produced by LLM Review"
    return "Round 1 — content produced by native extraction"


def quality_caption(page: dict[str, Any]) -> str | None:
    """Explain the automatic quality score that triggered OCR (NFR-19).

    Returns *None* when no score is available.  The configured threshold value
    itself is deliberately **not** duplicated here (it lives in the backend
    config, NFR-25) — the caption states the score and why it mattered.
    """
    score = page.get("quality_score")
    if score is None:
        return None
    if page.get("extraction_method") in ("ocr", "ocr_failed"):
        return (
            f"Automatic quality score: **{score:.2f}** — below the configured "
            "threshold, so the native result was discarded and OCR was used (FR-10)."
        )
    return f"Automatic quality score: **{score:.2f}** (above threshold — native result kept)."


def is_llm_extracted(page: dict[str, Any]) -> bool:
    """True when the page's content came from the vision LLM (NFR-24 flag)."""
    return page.get("extraction_method") == "llm_vision"


def is_awaiting_llm_review(page: dict[str, Any]) -> bool:
    """True while the page is queued/being re-extracted by the LLM (NFR-3)."""
    return page.get("status") == "llm_review"


def chunk_editable_text(chunk: dict[str, Any]) -> str:
    """Return the chunk's editable content as the review UI should show it.

    The backend stores a table chunk's content in ``table_markdown`` (its
    ``text`` column stays NULL — see ``ingestion_orchestrator._create_chunks``),
    so reading ``text`` alone would show tables as empty.  ``PATCH
    /pages/chunks/{id}`` only accepts ``text``, so that is what edits are sent
    as (see ``frontend/README.md`` for the resulting known limitation).
    """
    chunk_type = chunk.get("chunk_type")
    if chunk_type == "table":
        return chunk.get("text") or chunk.get("table_markdown") or ""
    if chunk_type == "image":
        return chunk.get("image_caption") or ""
    return chunk.get("text") or ""


def chunk_source_caption(page: dict[str, Any], chunk: dict[str, Any]) -> str:
    """Describe a chunk's provenance for the reviewer (NFR-27).

    Combines source page, chunk type, reading position, the extraction round
    that produced it and the chunk's own review state, so the user can verify
    correctness without opening the original PDF.
    """
    parts: list[Any] = [
        f"Page {page.get('page_number')}",
        CHUNK_TYPE_LABELS.get(chunk.get("chunk_type") or "", chunk.get("chunk_type") or "?"),
        f"reading order {chunk.get('reading_order')}",
        f"Round {page.get('review_round') or 1}",
    ]
    method = page.get("extraction_method")
    if method:
        parts.append(EXTRACTION_METHOD_LABELS.get(method, method))
    status = chunk.get("review_status")
    if status:
        parts.append(CHUNK_REVIEW_STATUS_LABELS.get(status, status))
    if chunk.get("excluded"):
        parts.append("marked excluded")
    return " · ".join(str(p) for p in parts)


# ──────────────────────────────────────────────────────────────────────
# Backend limits (GET /config/limits) — cached, never fatal
# ──────────────────────────────────────────────────────────────────────


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_limits() -> dict[str, Any]:
    """Fetch ``GET /config/limits`` once per 5 minutes; ``{}`` on any failure.

    Limits are display hints, so a backend hiccup must not break a page: the
    caller falls back to the OD-2/OD-7 defaults in ``_LIMIT_FALLBACKS``.
    """
    try:
        data = api.get_limits()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_limits() -> dict[str, int]:
    """Return the backend's k / upload / Raw-Mode limits with safe fallbacks.

    Reading these from the backend (rather than hardcoding them) keeps the UI in
    step with ``app/core/config.py`` without duplicating magic numbers, so the
    k-slider bound stays honest if the config changes (NFR-25).
    """
    raw = _fetch_limits() or {}
    limits: dict[str, int] = {}
    for key, fallback in _LIMIT_FALLBACKS.items():
        try:
            limits[key] = int(raw.get(key, fallback))
        except (TypeError, ValueError):
            limits[key] = fallback
    return limits


# ─────────────────────────────────────────────────────────────────────
# Session / navigation helpers
# ──────────────────────────────────────────────────────────────────────


def _redirect_to_login(message: str) -> None:
    """Clear the session, stash a one-shot flash message, go to login.

    Used for both logout and mid-session JWT expiry (Phase 12 error handling:
    "clear st.session_state and redirect back to the login screen … rather
    than repeatedly failing silently").  ``st.switch_page`` raises Streamlit's
    control-flow exception, so no code after a call to this helper runs.
    """
    st.session_state.clear()
    st.session_state["flash"] = message
    st.switch_page(LOGIN_PAGE)


def require_login() -> str:
    """Return the stored JWT, or bounce to the login screen (FR-2 / FR-3).

    Every page except the entry point calls this first, so an unauthenticated
    deep-link can never render data views.
    """
    token = st.session_state.get("token")
    if not token:
        _redirect_to_login("Please log in to continue.")
    return str(token)


def session_expired() -> None:
    """Handle a 401 from any call: drop the token and return to login."""
    _redirect_to_login("Your session expired, please log in again.")


def logout_and_redirect() -> None:
    """Call ``POST /auth/logout`` (best-effort), then clear the session (FR-2).

    Logout is stateless server-side, so a failure here is ignored on purpose:
    the client dropping the token *is* the logout.
    """
    try:
        api.logout(st.session_state.get("token"))
    except Exception:
        pass
    _redirect_to_login("You have been logged out.")


def show_flash() -> None:
    """Render and consume a one-shot message left by a redirect (if any)."""
    message = st.session_state.pop("flash", None)
    if message:
        st.info(message)


def sidebar_identity() -> None:
    """Render the shared sidebar: who is signed in, backend URL, logout.

    Showing ``API_BASE`` makes a "wrong port / backend not started" problem
    immediately diagnosable, and the logout button is the single place the
    token is dropped.
    """
    with st.sidebar:
        st.markdown(f"**{st.session_state.get('username', 'signed in')}**")
        st.caption(f"Backend: `{api.API_BASE}`")
        if st.button("Log out", key="ui_logout", use_container_width=True):
            logout_and_redirect()
        st.divider()


# ──────────────────────────────────────────────────────────────────────
# Uniform API error handling for every call site
# ──────────────────────────────────────────────────────────────────────


def handle_api_call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    """Call an :mod:`api_client` function and translate failures into UI.

    Guarantees the UI never surfaces a raw traceback for a backend problem
    (the Phase 12 error-handling requirement):

    * connection failure → "cannot reach the server" message;
    * timeout → slow-operation message (Raw Mode / LLM Review can be slow);
    * ``ApiError`` → the backend's own ``detail`` plus its ``error_code``, so an
      oversized upload (FR-5) or an OD-7 Raw-Mode limit is surfaced verbatim;
    * 401 (``None`` from the client) → session cleared + login redirect.

    Args:
        fn: An :mod:`api_client` function.
        *args: Positional arguments forwarded to *fn*.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The parsed JSON on success, otherwise *None* — callers must treat
        *None* as "do not continue with this action".
    """
    try:
        result = fn(*args, **kwargs)
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot reach the server at `{api.API_BASE}`. "
            "Is the FastAPI backend running (`uvicorn app.main:app` in `src/`)?"
        )
        return None
    except requests.exceptions.Timeout:
        st.error(
            "The backend did not respond in time. Raw Mode and LLM Review calls "
            "can take a while — please try again."
        )
        return None
    except api.ApiError as exc:
        st.error(f"**{exc.error_code}** — {exc.detail}")
        return None
    except requests.exceptions.RequestException as exc:
        st.error(f"Unexpected network error: {exc}")
        return None

    if result is None:
        # api_client only returns None for a 401 (every other failure raises).
        session_expired()
        return None
    return result
