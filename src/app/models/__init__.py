"""Database models for the PDF QA system.

Imports every ORM model so that ``Base.metadata`` is fully populated before
Alembic autogenerates migrations (otherwise Alembic silently produces an
empty migration).  Each entity lives in its own file and is re-exported here.
"""

from app.models.user import User
from app.models.document import Document
from app.models.page import Page
from app.models.chunk import Chunk
from app.models.embedding import Embedding
from app.models.query import Query
from app.models.answer import Answer
from app.models.feedback import Feedback
from app.models.token_usage import TokenUsage

__all__ = [
    "User",
    "Document",
    "Page",
    "Chunk",
    "Embedding",
    "Query",
    "Answer",
    "Feedback",
    "TokenUsage",
]