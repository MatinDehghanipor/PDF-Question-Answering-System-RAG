"""Embedding bookkeeping model.

This table is a bookkeeping/audit record for the "Embedding Service" and
"Vector Index / Store" components (SDD §4).  The actual float vectors live in
the external vector store (ChromaDB, added in Phase 6) — they are never
stored as SQL columns.  Only the link between a chunk and the embedding model
version used to embed it is recorded here.
"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Embedding(Base):
    """Audit record linking a chunk to the embedding model version used.

    NOTE: The real embedding vector is stored in Chroma (Phase 6), keyed by
    ``chunk_id`` and partitioned per user.  This SQL table only records which
    model version was used, so re-embeddings after model upgrades are
    traceable (dialect: sqlite/psql agnostic).

    Attributes:
        id: Surrogate primary key.
        chunk_id: Foreign key to the chunk that was embedded (unique, since a
            chunk is embedded with at most one model version at a time).
        embedding_model_version: Name/version string of the embedding model.
        chunk: The :class:`Chunk` this record refers to.
    """

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    embedding_model_version: Mapped[str] = mapped_column(String(128), nullable=False)

    # Relationship (string reference avoids circular imports)
    chunk: Mapped["Chunk"] = relationship()  # noqa: F821