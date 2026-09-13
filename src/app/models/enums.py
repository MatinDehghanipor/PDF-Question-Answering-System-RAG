"""Shared enum types for the PDF QA system database schema.

This module centralizes every enum used by the ORM models (SDD §7) so that all
status/type fields are constrained to valid values and stored consistently as
their lowercase string *values* (not Python member names) in the database.

Realizes SDD §7 requirement: "Use enums ... instead of free-text strings, to
prevent invalid values from ever being written."
"""

from enum import Enum


class DocumentStatus(str, Enum):
    """Lifecycle status of an uploaded PDF document (SDD §7)."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    AWAITING_FEEDBACK = "awaiting_feedback"
    READY = "ready"
    DISCARDED = "discarded"
    FAILED = "failed"


class PageStatus(str, Enum):
    """Lifecycle status of a single page during the ingestion pipeline (SDD §7)."""

    INITIAL_PROCESSING = "initial_processing"
    AWAITING_FEEDBACK = "awaiting_feedback"
    LLM_REVIEW = "llm_review"
    APPROVED = "approved"


class ExtractionMethod(str, Enum):
    """Method used to extract a page's content (SDD §7)."""

    NATIVE = "native"
    OCR = "ocr"
    LLM_VISION = "llm_vision"


class ChunkType(str, Enum):
    """Type of content a chunk represents (SDD §7)."""

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class ChunkReviewStatus(str, Enum):
    """Review state of an individual chunk (SDD §7)."""

    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class QueryMode(str, Enum):
    """Query mode: RAG (retrieval-augmented) or Raw (direct PDF to LLM)."""

    RAG = "rag"
    RAW = "raw"


class FeedbackRating(str, Enum):
    """User rating for an answer (SDD §7)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class TokenUsageContextType(str, Enum):
    """What operation consumed tokens (SDD §7)."""

    QUERY = "query"
    LLM_REVIEW = "llm_review"