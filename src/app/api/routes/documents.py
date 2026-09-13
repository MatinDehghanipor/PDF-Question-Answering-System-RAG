"""Document management API routes (Phase 0 stubs).

Implements the "Backend API / Orchestrator" document endpoints (SDD §4):
upload, list, and delete PDFs.  Real file storage + PDF splitting arrive in
Phase 2; these stubs only define the request/response shapes.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import DocumentStatus
from app.schemas.document import DocumentDeleteResponse, DocumentList, DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)) -> DocumentOut:
    """Upload a PDF file for ingestion.

    Realizes FR-4 (upload) — see Phase 2.

    Args:
        file: The uploaded PDF file.
        db: Database session (unused by the stub).

    Returns:
        A stub document record.
    """
    # TODO(Phase 2): validate size/type, persist to PDF File Storage, create
    # a Document row, and kick off page-level ingestion.
    return DocumentOut(id=1, user_id=1, filename=file.filename or "fake.pdf",
                       upload_date=datetime.utcnow(), status=DocumentStatus.UPLOADED,
                       page_count=None)


@router.get("", response_model=DocumentList)
def list_documents(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)) -> DocumentList:
    """List the current user's documents.

    Realizes FR-5 (list user documents, per-user isolation NFR-21) — see
    Phase 2.

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session (unused by the stub).

    Returns:
        A stub (empty) document list.
    """
    # TODO(Phase 2): query Document rows filtered by the authenticated user.
    return DocumentList(items=[], total=0)


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(document_id: int, db: Session = Depends(get_db)) -> DocumentDeleteResponse:
    """Delete an uploaded PDF (and all its derived data).

    Realizes FR-23 (delete document + cascade) — see Phase 2.

    Args:
        document_id: ID of the document to delete.
        db: Database session (unused by the stub).

    Returns:
        A stub deletion confirmation.
    """
    # TODO(Phase 2): remove the file from PDF File Storage and cascade-delete
    # Document / Page / Chunk / Embedding rows (SQLite FK pragma is already ON).
    return DocumentDeleteResponse(deleted=True, document_id=document_id)