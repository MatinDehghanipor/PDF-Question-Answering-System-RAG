"""Phase 12 client entry point — the registration / login gate (FR-1, FR-2).

This is the only screen a visitor can reach without a JWT.  It shows the
login and register forms until a token is in ``st.session_state``, then hands
over to ``pages/1_Documents.py``.

Streamlit reruns the *whole* script on every interaction, so the two mutating
calls (``POST /auth/login``, ``POST /auth/register``) live inside ``st.form``
blocks and fire only on an explicit submit — never at module level.

Backend contract used here:
    * ``POST /auth/register`` → 201 ``UserResponse``; 409 when the username or
      email is already taken (FR-1).
    * ``POST /auth/login`` → 200 ``{access_token, token_type}``; 401 for *both*
      an unknown user and a wrong password (anti-enumeration), and
      ``username`` may be either the username or the email (FR-2).
    * ``GET /health`` → 200 ``{"status": "ok"}`` (used for a clear
      "cannot reach the server" banner).
"""

import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

import requests  # noqa: E402
import streamlit as st  # noqa: E402

import api_client as api  # noqa: E402
import ui_helpers as uh  # noqa: E402

st.set_page_config(
    page_title="PDF QA System — Sign in",
    page_icon="📚",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ──────────────────────────────────────────────────────────────────────
# Backend reachability (Phase 12: "show a clear cannot-reach-the-server
# message, not a stack trace").  Cached briefly so a down backend does not
# add a 5 s wait to every rerun; the Retry button clears the cache.
# ──────────────────────────────────────────────────────────────────────


@st.cache_data(ttl=30, show_spinner=False)
def _health_ok() -> bool:
    """Return True when ``GET /health`` answers; False when unreachable."""
    try:
        api.health()
        return True
    except requests.exceptions.RequestException:
        return False


# ──────────────────────────────────────────────────────────────────────
# Auth actions — each one is triggered by an explicit form submit
# ──────────────────────────────────────────────────────────────────────


def _store_session(token: str, identifier: str) -> None:
    """Store the JWT + a display name and continue to the app (FR-2).

    Note: the backend has no ``/auth/me`` endpoint, so the stored display name
    is the identifier the user typed (username *or* email) — see
    ``frontend/README.md``.
    """
    st.session_state["token"] = token
    st.session_state["username"] = identifier
    st.switch_page(uh.DOCUMENTS_PAGE)


def _do_login(identifier: str, password: str) -> None:
    """Call ``POST /auth/login`` and handle all three outcomes (FR-2).

    A 401 is *expected* here (wrong credentials), so this deliberately does not
    use :func:`ui_helpers.handle_api_call` — that helper treats ``None`` as an
    expired session and would bounce the user back to this same page.
    """
    try:
        data = api.login(identifier, password)
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot reach the server at `{api.API_BASE}`. "
            "Is the FastAPI backend running (`uvicorn app.main:app` in `src/`)?"
        )
        return
    except api.ApiError as exc:
        st.error(f"**{exc.error_code}** — {exc.detail}")
        return
    except requests.exceptions.RequestException as exc:
        st.error(f"Unexpected network error: {exc}")
        return

    if data is None:
        # api_client maps the backend's generic 401 to None on purpose.  The
        # wording mirrors the backend's own message (no user enumeration).
        st.error("Incorrect username or password.")
        return

    _store_session(data["access_token"], identifier)


def _do_register(username: str, email: str, password: str) -> None:
    """Call ``POST /auth/register`` then sign the new user in (FR-1 → FR-2).

    Duplicate username/email surfaces the backend's own 409 detail through
    :func:`ui_helpers.handle_api_call`.
    """
    created = uh.handle_api_call(api.register, username, email, password)
    if created is None:
        return
    st.success(f"Account **{created.get('username', username)}** created — signing you in…")
    _do_login(username, password)


# ──────────────────────────────────────────────────────────────────────
# Page layout
# ──────────────────────────────────────────────────────────────────────

st.title("📚 PDF Question-Answering System")
st.caption(
    "Upload PDFs, review what was extracted page by page, then ask questions in "
    "**RAG Mode** (answered from approved, indexed content) or **Raw Mode** "
    "(the original file sent straight to the LLM)."
)

if st.session_state.get("token"):
    # Reached only when the user navigates back here while already signed in.
    st.success(f"You are already signed in as **{st.session_state.get('username')}**.")
    col_go, col_out = st.columns(2)
    with col_go:
        if st.button("Go to my documents", type="primary", use_container_width=True):
            st.switch_page(uh.DOCUMENTS_PAGE)
    with col_out:
        if st.button("Log out", use_container_width=True):
            uh.logout_and_redirect()
    st.stop()

uh.show_flash()

if not _health_ok():
    st.error(
        f"Cannot reach the backend API at `{api.API_BASE}`.  Start it with "
        "`uvicorn app.main:app --reload` from the `src/` directory (see "
        "`frontend/README.md`), then retry."
    )
    if st.button("Retry connection"):
        _health_ok.clear()
        st.rerun()

with st.expander("What you can do here", expanded=False):
    st.markdown(
        "1. **Upload** one or more PDFs — every page is extracted natively, "
        "scored, and OCR'd automatically when the quality is too low.\n"
        "2. **Review** each page's chunks (edit or exclude them) and approve "
        "them one by one or all at once.\n"
        "3. **Ask** questions in RAG Mode or Raw Mode, with the sources and the "
        "token usage shown for every answer.\n"
        "4. **Rate** answers and track your token usage over time."
    )

login_tab, register_tab = st.tabs(["Log in", "Create an account"])

with login_tab:
    with st.form("login_form"):
        login_identifier = st.text_input(
            "Username or email", max_chars=255, help="Either works (FR-2)."
        )
        login_password = st.text_input("Password", type="password", max_chars=128)
        login_submitted = st.form_submit_button(
            "Log in", type="primary", use_container_width=True
        )

    if login_submitted:
        if not login_identifier.strip() or not login_password:
            st.warning("Enter both your username/email and your password.")
        else:
            _do_login(login_identifier.strip(), login_password)

with register_tab:
    with st.form("register_form"):
        reg_username = st.text_input(
            "Username", max_chars=64, help="3–64 characters (FR-1)."
        )
        reg_email = st.text_input("Email", max_chars=254)
        reg_password = st.text_input(
            "Password", type="password", max_chars=128, help="At least 8 characters."
        )
        reg_password2 = st.text_input("Confirm password", type="password", max_chars=128)
        reg_submitted = st.form_submit_button(
            "Create account", type="primary", use_container_width=True
        )

    if reg_submitted:
        # Mirror the backend's own rules (app/schemas/user.py) so the user gets
        # an instant hint instead of a 422 round-trip.
        if not (reg_username.strip() and reg_email.strip() and reg_password):
            st.warning("Username, email and password are all required.")
        elif len(reg_username.strip()) < 3:
            st.warning("Username must be at least 3 characters.")
        elif len(reg_password) < 8:
            st.warning("Password must be at least 8 characters.")
        elif reg_password != reg_password2:
            st.warning("The two passwords do not match.")
        else:
            _do_register(reg_username.strip(), reg_email.strip(), reg_password)

st.divider()
st.caption(
    f"Backend: `{api.API_BASE}` · A full page refresh signs you out (the session "
    "token is held in Streamlit's in-memory session state)."
)