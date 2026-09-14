"""Pydantic schemas for document upload/list/delete endpoints.

Mirrors :mod:`app.models.document`.  Request/response shapes for
POST/GET/DELETE /documents (upload, list per user, delete — realized in
Phase 2 / FR-4, FR-5, FR-23).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DocumentStatus


class DocumentOut(BaseModel):
    """Public representation of a document (list view)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    filename: str
    upload_date: datetime
    status: DocumentStatus
    page_count: int | None = None


class PageSummary(BaseModel):
    """Lightweight page representation included in document detail responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    page_number: int
    status: str
    extraction_method: str | None = None
    quality_score: float | None = None
    review_round: int


class DocumentDetailOut(BaseModel):
    """Full document detail including per-page statuses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    filename: str
    upload_date: datetime
    status: DocumentStatus
    page_count: int | None = None
    pages: list[PageSummary] = []


class DocumentList(BaseModel):
    """Paginated list of documents owned by a user."""

    items: list[DocumentOut]
    total: int


class DocumentDeleteResponse(BaseModel):
    """Confirmation body for DELETE /documents/{id} (FR-23)."""

    deleted: bool
    document_id: int


class ApproveAllResponse(BaseModel):
    """Confirmation of an Approve-All action (FR-13, NFR-11)."""

    document_id: int
    pages_approved: int
    message: str


class DocumentUploadError(BaseModel):
    """Error details for a single file in a batch upload."""

    filename: str
    error: str


class BatchUploadResponse(BaseModel):
    """Response body for POST /documents with one or more files."""

    documents: list[DocumentOut]
    errors: list[DocumentUploadError] = []