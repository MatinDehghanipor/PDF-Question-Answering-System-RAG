"""SQLAlchemy engine, session factory, and declarative base.

This module implements the database layer of the backend (SDD §3, §7).
It creates the SQLAlchemy ``engine``, ``SessionLocal`` session factory, the
``Base`` declarative base used by all model classes, and a ``get_db()``
stacked dependency for FastAPI route handlers.

SQLite does not enforce foreign keys by default; we enable
``PRAGMA foreign_keys=ON`` on every connection so that cascading deletes
(needed later for FR-23) behave correctly.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# connect_args pragma is NOT a valid SQLAlchemy create_engine key; instead we
# enable SQLite FK enforcement with a connection event listener below.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        """Enable SQLite foreign-key enforcement on every new connection.

        SQLite does not enforce foreign keys by default; without this,
        cascading deletes (needed later for FR-23) would silently fail.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base class shared by every ORM model in the project."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it afterwards.

    Yields:
        Session: a SQLAlchemy ORM session bound to the configured database.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()