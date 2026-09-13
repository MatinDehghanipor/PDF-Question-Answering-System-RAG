"""User account model.

Implements the "User Accounts DB" component (SDD §4): stores registered users
and their hashed credentials.  Also the root of the per-user isolation chain —
every other table is linked (directly or transitively) back to this table so
NFR-21 (per-user isolation) can be enforced at the query layer from Phase 1.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """A registered user of the system.

    Attributes:
        id: Surrogate primary key.
        username: Unique display/login name.
        email: Unique email address.
        password_hash: Hashed password (set by Auth Service, Phase 1).
        created_at: Timestamp of account creation.
        documents: Documents uploaded by this user (one-to-many).
        queries: Queries issued by this user (one-to-many).
        token_usage: Token usage records attributed to this user (one-to-many).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships (string references avoid circular imports with other models)
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="owner", cascade="all, delete-orphan"
    )
    queries: Mapped[list["Query"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    token_usage: Mapped[list["TokenUsage"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )