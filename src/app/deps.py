"""Shared FastAPI dependencies.

Re-exports the database session dependency from :mod:`app.core.database` and
provides the authentication dependency stub that will be wired into
protected routes starting in Phase 1.
"""

from app.core.database import Base, SessionLocal, engine, get_db

__all__ = ["Base", "SessionLocal", "engine", "get_db", "get_current_user"]


def get_current_user():
    """Return the authenticated user for the current request.

    Stub for Phase 1 — validates the JWT bearer token and loads the
    corresponding :class:`User` row.  Until then it always raises
    ``NotImplementedError`` so no route can silently rely on it.

    Realizes FR-2 session validation / NFR-21 per-user isolation once
    implemented.

    Raises:
        NotImplementedError: Always, until Phase 1 replaces this stub.
    """
    # TODO(Phase 1): decode JWT, load the User, and raise 401 on failure.
    raise NotImplementedError("Auth dependency stub — implemented in Phase 1")