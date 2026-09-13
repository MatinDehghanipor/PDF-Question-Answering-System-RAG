"""Real authentication service: password hashing and JWT issue/validation.

Implements the "Auth Service" component (SDD §4): registration, login/logout,
and session/token validation.

Realizes:
    * FR-1  — register a new user account.
    * FR-2  — log in / log out; maintain a token identifying the authenticated
              user for subsequent requests.
    * FR-3 / NFR-21 — per-user isolation starts here: every returned
              :class:`User` carries the id that all later queries must scope by.
    * NFR-20 — passwords are stored only as a bcrypt hash (strong one-way
              hash, never plain text).
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User

# ---------------------------------------------------------------------------
# Password hashing (NFR-20)
# ---------------------------------------------------------------------------
# bcrypt automatically salts each hash, satisfying NFR-20's "strong one-way
# hash, never plain text".  NOTE: bcrypt only considers the first 72 bytes of
# the password; extremely long passwords silently truncate.  Our Pydantic
# schema caps password length (max 128 chars) so this is not a practical
# concern here, but it is worth documenting at the hashing site.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class DuplicateUserError(Exception):
    """Raised when a username or email address is already registered.

    Translated by the route layer to HTTP 409 Conflict (not a raw DB
    IntegrityError — see Phase 1 error-handling requirements).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (auto-salted).

    Realizes NFR-20: the hash — never the plaintext — is what gets stored.

    Args:
        password: Plaintext password from the registration request.

    Returns:
        A bcrypt hash string suitable for storage in ``users.password_hash``.

    Note:
        bcrypt's 72-byte input limit means extremely long passwords are
        silently truncated by the backend; the register schema's max_length
        keeps this non-issue in practice.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Uses ``passlib``'s constant-time comparison (never compares plaintext
    directly), satisfying NFR-20's "strong one-way hash" requirement.

    Args:
        plain_password: Password supplied at login.
        password_hash:  Hash stored in ``users.password_hash``.

    Returns:
        ``True`` if the password matches the hash, else ``False``.
    """
    return pwd_context.verify(plain_password, password_hash)


# ---------------------------------------------------------------------------
# JWT creation / decoding (FR-2)
# ---------------------------------------------------------------------------
# A JWT is a signed (not encrypted) token.  We use the stateless bearer-token
# convention from FastAPI's OAuth2PasswordBearer / OAuth2PasswordRequestForm
# without a full OAuth2 identity provider (SDD §3).
#
# Claims:
#   * ``sub`` — the user id as a string (RFC 7519 requires a string subject).
#   * ``exp`` — UTC expiry timestamp.  Always set, so jose raises
#     ``ExpiredSignatureError`` naturally and no token can live forever.
#
# ``logout`` is stateless: the client discards its copy of the token.  No
# server-side blacklist is in scope for this version, so logout is documented
# in the route as client-side only.


def create_access_token(subject: str | int, expires_minutes: int | None = None) -> str:
    """Create a signed HS256 JWT for a user.

    Realizes FR-2: issues the session token that identifies the authenticated
    user on all subsequent requests.

    Args:
        subject: The user id (int) or string id to place in the ``sub`` claim.
        expires_minutes: Override for ``settings.JWT_EXPIRE_MINUTES``.  If
            ``None``, the configured default (24h) is used.

    Returns:
        The encoded JWT string.  The token is signed with HMAC-SHA256 using
        ``settings.JWT_SECRET_KEY`` (from ``.env`` — never hardcoded), which
        proves it was issued by this server and has not been tampered with.

    Raises:
        jose.JWTError: If the token cannot be encoded (should not happen).
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else settings.JWT_EXPIRE_MINUTES
    )
    to_encode = {"sub": str(subject), "exp": expire}
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT.

    Realizes FR-2 / FR-3: verifies signature, expiry, and untampered claims
    before a protected endpoint trusts the token.

    Args:
        token: The raw ``Authorization: Bearer <token>`` value.

    Returns:
        The decoded payload dict (containing at least ``sub``).

    Raises:
        jose.ExpiredSignatureError: If the ``exp`` claim is in the past.
        jose.JWTError: On a bad signature, malformed token, or any other
            validation failure.  Callers (``app.deps.get_current_user``) treat
            every such failure identically as "could not validate credentials".
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


# ---------------------------------------------------------------------------
# Registration / authentication (FR-1, FR-2)
# ---------------------------------------------------------------------------


def register_user(
    db: Session,
    username: str,
    email: str,
    password: str,
) -> User:
    """Create and persist a new user with a bcrypt-hashed password.

    Realizes FR-1 (registration) and NFR-20 (hash, never plaintext).
    Enforces uniqueness of both username and email, mapping any conflict or
    race-condition IntegrityError to a :class:`DuplicateUserError` so the
    route can respond 409 instead of leaking a raw DB error.

    Args:
        db: Active database session.
        username: Unique login/display name.
        email: Unique email address.
        password: Plaintext password (will be bcrypt-hashed before storage;
            the plaintext is never persisted or returned).

    Returns:
        The newly created :class:`User` ORM object (its ``password_hash`` is
        present on the object but must never be included in any response
        schema — see ``app/schemas/user.py``).

    Raises:
        DuplicateUserError: If the username or email already exists.
    """
    # Re-check before inserting so a conflict surfaces as a clear 409 rather
    # than a raw DB IntegrityError.
    existing = (
        db.query(User)
        .filter(or_(User.username == username, User.email == email))
        .first()
    )
    if existing is not None:
        if existing.username == username:
            raise DuplicateUserError("Username is already registered")
        raise DuplicateUserError("Email is already registered")

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Covers the rare concurrent-registration race where the unique
        # constraints fire between our SELECT and this INSERT.
        db.rollback()
        raise DuplicateUserError("Username or email is already registered") from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, username_or_email: str, password: str) -> User | None:
    """Look up a user by username or email and verify their password.

    Realizes FR-2 (login).  Returns a single generic failure (``None``) for
    both "unknown user" and "wrong password" so the login endpoint responds
    401 with the identical message ("Incorrect username or password") — this
    avoids revealing whether a username exists (anti-enumeration).

    Args:
        db: Active database session.
        username_or_email: Login identifier (username or email).
        password: Plaintext password to verify.

    Returns:
        The authenticated :class:`User` on success, or ``None`` if the user
        is unknown or the password does not match the stored hash.
    """
    user = (
        db.query(User)
        .filter(or_(User.username == username_or_email, User.email == username_or_email))
        .first()
    )
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user