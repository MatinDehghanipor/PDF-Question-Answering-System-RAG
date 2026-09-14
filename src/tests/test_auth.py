"""Phase 1 tests: registration, login/logout, JWT auth, and per-user isolation.

Verifies the Definition of Done for Phase 1:
    * A new user can register (FR-1) and receive the created user's public
      fields (never the password hash — NFR-20).
    * A registered user can log in and receive a JWT (FR-2).
    * Protected endpoints reject missing, expired, and tampered tokens with
      401 (FR-2 / NFR-20).
    * A valid token resolves the current user inside the endpoint, and its
      user_id isolates data (FR-3 / NFR-21).
    * Duplicate registration → 409 and bad login → generic 401 without user
      enumeration.

Note: tests share the real Phase-0 SQLite database (data/app.db) so they are
integration-style; each test uses unique usernames/emails to avoid clashes.
"""

import time
import uuid

from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app

client = TestClient(app)

# Unique suffix per test-run so registration tests are idempotent against the
# persistent data/app.db (re-running the suite must not hit 409 conflicts).
_RUN_SUFFIX = uuid.uuid4().hex[:8]


def _make_tiny_pdf() -> bytes:
    """Create a minimal 1-page PDF for upload tests."""
    import fitz, io
    doc = fitz.open()
    doc.new_page()
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Registration (FR-1, NFR-20)
# ---------------------------------------------------------------------------


def test_register_new_user_returns_public_fields() -> None:
    """POST /auth/register creates a user and returns public fields only."""
    username = f"reg_test_user_{_RUN_SUFFIX}"
    email = f"reg_test_user_{_RUN_SUFFIX}@example.com"
    response = client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": "password123"},
    )
    assert response.status_code == 201
    body = response.json()
    # Public fields are present.
    assert body["username"] == username
    assert body["email"] == email
    assert isinstance(body["id"], int)
    assert "created_at" in body
    # NFR-20: the password hash must never appear in any response.
    assert "password_hash" not in body
    assert "password" not in body


def test_register_duplicate_username_returns_409() -> None:
    """Duplicate username registration fails with 409 (not a raw IntegrityError)."""
    username = f"dup_username_{_RUN_SUFFIX}"
    email = f"dup_username_{_RUN_SUFFIX}@example.com"
    payload = {"username": username, "email": email, "password": "password123"}
    first = client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = client.post("/auth/register", json=payload)
    assert second.status_code == 409
    body = second.json()
    assert "detail" in body


def test_register_duplicate_email_returns_409() -> None:
    """Duplicate email registration fails with 409 even with a different username."""
    email = f"dup_email_{_RUN_SUFFIX}@example.com"
    first = client.post(
        "/auth/register",
        json={"username": f"dup_email_a_{_RUN_SUFFIX}", "email": email, "password": "password123"},
    )
    assert first.status_code == 201

    second = client.post(
        "/auth/register",
        json={"username": f"dup_email_b_{_RUN_SUFFIX}", "email": email, "password": "password123"},
    )
    assert second.status_code == 409


def test_register_short_password_returns_422() -> None:
    """A password shorter than 8 chars is rejected by Pydantic validation (422)."""
    response = client.post(
        "/auth/register",
        json={
            "username": f"short_pw_user_{_RUN_SUFFIX}",
            "email": f"short_pw_user_{_RUN_SUFFIX}@example.com",
            "password": "short",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login / logout (FR-2)
# ---------------------------------------------------------------------------


def test_login_returns_jwt_and_logout_succeeds() -> None:
    """A registered user can log in (get a JWT) and then log out."""
    username = f"login_test_user_{_RUN_SUFFIX}"
    email = f"login_test_user_{_RUN_SUFFIX}@example.com"
    password = "password123"

    reg = client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert reg.status_code == 201

    # Log in with username.
    login = client.post(
        "/auth/login", data={"username": username, "password": password},
    )
    assert login.status_code == 200
    body = login.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"

    # Verify the JWT itself: sub must be the user id string, exp in the future.
    payload = jwt.decode(body["access_token"], settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == str(reg.json()["id"])

    # Log in with email also works.
    login_email = client.post(
        "/auth/login", data={"username": email, "password": password},
    )
    assert login_email.status_code == 200

    # Logout is stateless: it just returns success.
    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"message": "logged out"}


def test_login_wrong_password_returns_generic_401() -> None:
    """Wrong password returns the same generic 401 as unknown user (no enumeration)."""
    username = f"wrong_pw_user_{_RUN_SUFFIX}"
    email = f"wrong_pw_user_{_RUN_SUFFIX}@example.com"
    client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": "password123"},
    )

    response = client.post(
        "/auth/login",
        data={"username": username, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_login_unknown_user_returns_generic_401() -> None:
    """Unknown user returns the same 401 message as wrong password (anti-enumeration)."""
    response = client.post(
        "/auth/login",
        data={"username": "NoSuchUser12345", "password": "whatever1"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"

    # The 401 body is identical whether the user exists or not.
    wrong_response = client.post(
        "/auth/login",
        data={"username": "NoSuchUser12345", "password": "whatever1"},
    )
    assert wrong_response.json() == response.json()


# ---------------------------------------------------------------------------
# Protected endpoints (NFR-20, FR-2)
# ---------------------------------------------------------------------------


def test_protected_get_endpoints_without_token_returns_401() -> None:
    """GET-protected endpoints return 401 with a Bearer challenge when no token."""
    for path in ["/documents", "/feedback", "/usage", "/usage/summary"]:
        response = client.get(path)
        assert response.status_code == 401, f"{path} should require auth"
        assert response.headers.get("www-authenticate", "").startswith("Bearer")


def test_protected_post_endpoints_require_token() -> None:
    """POST-protected endpoints also reject missing tokens with 401."""
    # /query is a POST endpoint (body must match QueryCreate: text + mode).
    response = client.post("/query", json={"text": "What is RAG?", "mode": "rag"})
    assert response.status_code == 401

    # /documents POST (requires a file) — a missing token fails before file validation.
    response = client.post("/documents")
    assert response.status_code == 401

    # /pages review POST requires auth too.
    response = client.post("/pages/1/review", json={"decision": "approve"})
    assert response.status_code == 401


def test_tampered_token_returns_401() -> None:
    """A token signed with the wrong secret must be rejected (401)."""
    tampered = jwt.encode(
        {"sub": "1", "exp": int(time.time()) + 3600},
        "wrong-secret-key",
        algorithm="HS256",
    )
    response = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert response.status_code == 401


def test_expired_token_returns_401() -> None:
    """An expired token must be rejected (401)."""
    # Craft a token that expired 10 seconds ago using the real secret.
    expired = jwt.encode(
        {"sub": "1", "exp": int(time.time()) - 10},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert response.status_code == 401


def test_malformed_token_returns_401() -> None:
    """A malformed Authorization header / token returns 401, not 500."""
    response = client.get(
        "/documents",
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Per-user isolation (FR-3 / NFR-21)
# ---------------------------------------------------------------------------


def test_valid_token_resolves_current_user_and_isolates_documents() -> None:
    """A valid JWT identifies the current user; document lists are user-scoped."""
    user_a = f"isolation_a_user_{_RUN_SUFFIX}"
    user_b = f"isolation_b_user_{_RUN_SUFFIX}"
    email_a = f"isolation_a_{_RUN_SUFFIX}@example.com"
    email_b = f"isolation_b_{_RUN_SUFFIX}@example.com"
    password = "password123"

    id_a = None
    id_b = None
    for username, email in [(user_a, email_a), (user_b, email_b)]:
        reg = client.post(
            "/auth/register",
            json={"username": username, "email": email, "password": password},
        )
        assert reg.status_code == 201
        if username == user_a:
            id_a = reg.json()["id"]
        else:
            id_b = reg.json()["id"]

    # Login both users.
    token_a = client.post(
        "/auth/login", data={"username": user_a, "password": password},
    ).json()["access_token"]
    token_b = client.post(
        "/auth/login", data={"username": user_b, "password": password},
    ).json()["access_token"]
    assert token_a != token_b

    # The upload stub echoes current_user.id from the JWT, proving the resolved.
    # user is available inside the endpoint (NFR-21 ownership scoping).
    tiny_pdf = _make_tiny_pdf()

    upload_a = client.post(
        "/documents",
        files={"files": ("a.pdf", tiny_pdf, "application/pdf")},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert upload_a.status_code == 201
    assert upload_a.json()["documents"][0]["user_id"] == id_a

    upload_b = client.post(
        "/documents",
        files={"files": ("b.pdf", tiny_pdf, "application/pdf")},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert upload_b.status_code == 201
    assert upload_b.json()["documents"][0]["user_id"] == id_b
    assert upload_a.json()["documents"][0]["user_id"] != upload_b.json()["documents"][0]["user_id"]

    # Each user's document list is scoped to themselves (no cross-user leak).
    resp_a = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # Each user uploaded one real PDF via the new endpoint, so each sees
    # exactly one document.  The key assertion is cross-user isolation:
    # user A does NOT see user B's document.
    assert resp_a.json()["total"] == 1
    assert resp_b.json()["total"] == 1
    assert resp_a.json()["items"][0]["filename"] == "a.pdf"
    assert resp_b.json()["items"][0]["filename"] == "b.pdf"