"""Pydantic schemas for user registration, login, and token responses.

Mirrors :mod:`app.models.user`.  These shapes define the /auth endpoints'
request and response bodies.  Password fields are never echoed back in
responses (schemas ``UserOut``/``Token`` exclude ``password_hash``).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Request body for POST /auth/register (realizes FR-1 — Phase 1)."""

    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Request body for POST /auth/login (realizes FR-2 — Phase 1)."""

    username: str
    password: str


class UserOut(BaseModel):
    """Public user representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    created_at: datetime


class Token(BaseModel):
    """JWT token pair returned after login/register (Phase 1)."""

    access_token: str
    token_type: str = "bearer"