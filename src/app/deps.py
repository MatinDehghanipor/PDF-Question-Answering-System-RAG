"""Shared FastAPI dependencies.

Re-exports the database session dependency from :mod:`app.core.database` and
provides the reusable ``get_current_user`` dependency that every protected
endpoint uses to resolve the authenticated user and scope all database queries
to ``user_id`` (NFR-21 / FR-3).
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from sqlalchemy.orm import Session

from app.core.database import Base, SessionLocal, engine, get_db
from app.models.user import User
from app.services.auth_service import decode_access_token

__all__ = ["Base", "SessionLocal", "engine", "get_db", "get_current_user"]

# Extracts ``Authorization: Bearer <token>`` from the request header.  This is
# only the token-extraction mechanism (SDD §3) — the project does not implement
# a full OAuth2 identity provider.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a JWT bearer token.

    Realizes FR-2 (session/token validation) and FR-3 / NFR-21 (every
    protected endpoint starts from a concrete :class:`User` whose id must
    scope all subsequent database queries).

    The token is decoded with the server's HMAC secret, which verifies the
    signature (token was issued by this server and not tampered with) and the
    ``exp`` claim (token has not expired).  On any failure — bad signature,
    expired, malformed, or a ``sub`` that does not match any user — the same
    401 "Could not validate credentials" is returned so no route can silently
    treat an invalid token as authenticated.

    Args:
        token: The raw bearer token extracted by ``OAuth2PasswordBearer``.
        db: Database session.

    Returns:
        The :class:`User` ORM object corresponding to the token's ``sub``
        claim.  Endpoints receive this as ``current_user`` and MUST filter
        every query for user-owned data by ``current_user.id``.

    Raises:
        HTTPException: 401 with ``WWW-Authenticate: Bearer`` if the token is
            missing/malformed/expired/tampered, or if the user no longer
            exists in the database.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user_id = int(user_id)
    except (JWTError, ValueError):
        # jose raises ExpiredSignatureError / JWTError for expired or
        # tampered/malformed tokens; ValueError covers a non-numeric sub.
        raise credentials_exception from None

    user = db.get(User, user_id)
    if user is None:
        # Valid signature but the account was deleted — treat as unauthenticated.
        raise credentials_exception
    return user