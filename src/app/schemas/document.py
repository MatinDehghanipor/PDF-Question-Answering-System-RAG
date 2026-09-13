"""Pydantic schemas for document upload/list/delete endpoints.

Mirrors :mod:`app.models.document`.  Request/response shapes for
POST/GET/DELETE /documents (upload, list per user, delete — realized in
Phase 2 / FR-4, FR-5, FR-23).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DocumentStatus


class DocumentOut(BaseModel):
    """Public representation of a document."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    filename: str
    upload_date: datetime
    status: DocumentStatus
    page_count: int | None = None


class DocumentList(BaseModel):
    """Paginated list of documents owned by a user."""

    items: list[DocumentOut]
    total: int


class DocumentDeleteResponse(BaseModel):
    """Confirmation body for DELETE /documents/{id} (FR-23)."""

    deleted: bool
    document_id: int