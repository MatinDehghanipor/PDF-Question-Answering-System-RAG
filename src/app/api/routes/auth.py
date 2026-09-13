"""Authentication API routes (real implementation, Phase 1).

Implements the "Auth Service" controller endpoints (SDD §4): registration,
login, and logout.

Realizes:
    * FR-1  — registration: accepts username/email + password, rejects
              duplicates with 409, stores only the bcrypt hash (NFR-20).
    * FR-2  — login: verifies credentials and issues a signed JWT
              (``sub`` = user id, ``exp`` = expiry) used to scope all
              subsequent requests to that user.
    * NFR-20 — passwords are hashed (bcrypt) before storage, never plaintext.

NOTE — logout is stateless: with stateless JWTs there is no server-side
session to destroy and no token blacklist in scope for this version, so
clients are responsible for discarding their copy of the token.  POST
/auth/logout exists for API completeness (FR-2's wording) and simply returns
success.

STANDING RULE (applies to every route file from Phase 1 onward): every
database query that reads or writes user-owned data (Document/Page/Chunk/
Query/Answer/Feedback/TokenUsage) MUST filter by the current user's id, e.g.
``db.query(Document).filter(Document.user_id == current_user.id, ...)``, so
FR-3 / NFR-21 (per-user isolation) is always enforced at the query layer.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.user import TokenResponse, UserRegisterRequest, UserResponse
from app.services.auth_service import (
    DuplicateUserError,
    authenticate_user,
    create_access_token,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: UserRegisterRequest,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Register a new user account (FR-1).

    Accepts username, email, and password.  The password is bcrypt-hashed
    (NFR-20) and only ``password_hash`` is persisted — the plaintext is never
    stored or echoed.  Duplicate username/email → 409 Conflict.

    Args:
        body: Registration credentials.
        db: Database session.

    Returns:
        The created user's public fields (id, username, email, created_at).
        The password hash is never included (see ``UserResponse``).

    Raises:
        HTTPException: 409 if the username or email is already registered.
    """
    try:
        user = register_user(db, body.username, body.email, body.password)
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate a user and issue a JWT (FR-2).

    Uses FastAPI's ``OAuth2PasswordRequestForm`` so login is testable directly
    from Swagger UI (``application/x-www-form-urlencoded``).  ``username``
    accepts either the username or the email address.

    On success a JWT is returned with claims ``sub`` = user id and
    ``exp`` = now + ``settings.JWT_EXPIRE_MINUTES``.  On failure (unknown user
    OR wrong password) the same generic 401 is returned for both cases so the
    response never reveals whether a username exists (anti-enumeration).

    Args:
        form_data: Form-encoded ``username`` + ``password``.
        db: Database session.

    Returns:
        A bearer token: ``{"access_token": <jwt>, "token_type": "bearer"}``.

    Raises:
        HTTPException: 401 with "Incorrect username or password".
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user.id)
    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/logout")
def logout() -> dict[str, str]:
    """Log out the current user (FR-2, stateless).

    This endpoint exists for API completeness.  Because JWTs are stateless and
    no server-side token blacklist is in scope for this version, actual
    invalidation is performed by the **client discarding the token**: simply
    stop sending the ``Authorization: Bearer <token>`` header on subsequent
    requests (and remove it from any client-side storage).

    Returns:
        A success message confirming the client should discard its token.
    """
    return {"message": "logged out"}