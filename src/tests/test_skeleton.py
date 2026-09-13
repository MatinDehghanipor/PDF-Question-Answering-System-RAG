"""Phase 0 smoke tests for the project skeleton.

Verifies the app imports cleanly, the health endpoint works, and all route
groups from the final API surface are registered.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    """GET /health returns 200 with a JSON ok payload."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_all_router_groups_present() -> None:
    """Swagger/OpenAPI exposes every endpoint group the finished system needs."""
    paths = {route.path for route in app.routes}
    expected_prefixes = [
        "/auth",
        "/documents",
        "/pages",
        "/query",
        "/feedback",
        "/usage",
        "/health",
    ]
    for prefix in expected_prefixes:
        assert any(p.startswith(prefix) for p in paths), f"Missing route group {prefix}"


def test_unknown_route_returns_json_404() -> None:
    """Unknown routes return the consistent JSON error shape (FR-36 foundation)."""
    response = client.get("/definitely-not-a-route")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "not_found"


def test_stub_registration_returns_created_user() -> None:
    """Auth register (Phase 1) accepts the final request shape and returns the user."""
    import uuid

    username = f"skeleton_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "email": email,
            "password": "password123",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert "username" in body
    assert "email" in body
