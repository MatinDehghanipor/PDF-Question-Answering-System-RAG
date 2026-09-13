"""Answer model.

Stores the LLM-generated answer for a query (SDD §7).  For RAG Mode,
``source_chunk_ids`` records which top-k chunks were retrieved and used;
for Raw Mode it remains NULL since no chunk retrieval happens.
"""

from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Answer(Base):
    """The generated answer text for a single query.

    Attributes:
        id: Surrogate primary key.
        query_id: Foreign key to the query this answers (one-to-one).
        generated_text: The answer text produced by the LLM.
        source_chunk_ids: Ordered list of chunk id integers used as RAG
            context; NULL for Raw Mode answers.
        llm_model_version: Model name/version that generated the answer.
        query: The :class:`Query` this answers.
    """

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query_id: Mapped[int] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    llm_model_version: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationship (string reference avoids circular imports)
    query: Mapped["Query"] = relationship(back_populates="answer")  # noqa: F821