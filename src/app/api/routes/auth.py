"""Authentication API routes (Phase 0 stubs).

Implements the "Auth Service" controller endpoints (SDD §4): registration,
login, and logout.  Real password hashing and JWT issuing arrive in Phase 1;
these stubs only define the request/response shapes so Swagger reflects the
final API.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.user import Token, UserCreate, UserLogin

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token)
def register(body: UserCreate, db: Session = Depends(get_db)) -> Token:
    """Register a new user account.

    Realizes FR-1 (user registration) — see Phase 1.

    Args:
        body: Registration credentials.
        db: Database session (unused by the stub).

    Returns:
        A fake JWT token marked as a stub.
    """
    # TODO(Phase 1): hash the password, persist the user, issue a real JWT.
    return Token(access_token="stub.jwt.token", token_type="bearer")


@router.post("/login", response_model=Token)
def login(body: UserLogin, db: Session = Depends(get_db)) -> Token:
    """Authenticate a user and return a JWT.

    Realizes FR-2 (user login) — see Phase 1.

    Args:
        body: Login credentials.
        db: Database session (unused by the stub).

    Returns:
        A fake JWT token marked as a stub.
    """
    # TODO(Phase 1): verify credentials, issue a real JWT.
    return Token(access_token="stub.jwt.token", token_type="bearer")


@router.post("/logout", response_model=dict[str, bool])
def logout(db: Session = Depends(get_db)) -> dict[str, bool]:
    """Invalidate the current session/token.

    Realizes FR-3 (logout) — see Phase 1.

    Args:
        db: Database session (unused by the stub).

    Returns:
        A stub confirmation payload.
    """
    # TODO(Phase 1): revoke/blacklist the JWT on the server if applicable.
    return {"logged_out": True, "_stub": True}