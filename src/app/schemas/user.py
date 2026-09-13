"""Pydantic schemas for user registration, login, and token responses.

Mirrors :mod:`app.models.user`.  These shapes define the /auth endpoints'
request and response bodies.

Security note (NFR-20): no response schema in this module ever includes
``password_hash`` (or any password field).  ``UserResponse`` exposes only the
user's public fields (id, username/email, created_at), so a user's password
hash can never leak through the API.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Request body for POST /auth/register (realizes FR-1).

    Attributes:
        username: Unique login/display name (3–64 chars).
        email: Unique email address (validated by ``EmailStr``).
        password: Plaintext password.  Enforced minimum length of 8 chars
            (see Phase 1 error handling: missing/short password → 422).
    """

    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    """Request body for POST /auth/login (realizes FR-2).

    ``username`` accepts either the username or the email address; the Auth
    Service resolves it.  This schema is kept for programmatic API clients;
    the Swagger-UI-friendly ``OAuth2PasswordRequestForm`` (application/x-www-
    form-urlencoded) is also accepted by the login route.
    """

    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    """Public user representation returned to clients.

    Never exposes ``password_hash`` (NFR-20).  Returned by
    POST /auth/register and by the ``get_current_user`` dependency wherever a
    route needs to echo the current user.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT bearer token returned after login/register (FR-2).

    Attributes:
        access_token: The signed JWT string.
        token_type: Always ``"bearer"`` per the OAuth2 bearer convention.
    """

    access_token: str
    token_type: str = "bearer"