"""Document management API routes (Phase 0 stubs wired for auth in Phase 1).

Implements the "Backend API / Orchestrator" document endpoints (SDD §4):
upload, list, and delete PDFs.  Real file storage + PDF splitting arrive in
Phase 2; these endpoints still return stub payloads, but authentication is
already wired in so Phase 2 never has to retrofit it.

STANDING RULE (applies to every route file from Phase 1 onward): every
database query that reads or writes user-owned data (Document/Page/Chunk/
Query/Answer/Feedback/TokenUsage) MUST filter by the current user's id, e.g.
``db.query(Document).filter(Document.user_id == current_user.id, ...)``, so
FR-3 / NFR-21 (per-user isolation) is always enforced at the query layer.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.user import User
from app.schemas.document import DocumentDeleteResponse, DocumentList, DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentOut:
    """Upload a PDF file for ingestion (FR-4 — Phase 2).

    Requires authentication (NFR-20): the stub returns a document record owned
    by ``current_user``, demonstrating that the resolved user is available
    inside the endpoint and that any real Phase-2 query will be scoped by
    ``current_user.id`` (NFR-21).

    Args:
        file: The uploaded PDF file.
        db: Database session (unused by the stub).
        current_user: The authenticated user (JWT-derived).

    Returns:
        A stub document record owned by the current user.
    """
    # TODO(Phase 2): validate size/type, persist to PDF File Storage, create
    # a Document row, and kick off page-level ingestion.
    return DocumentOut(id=1, user_id=current_user.id, filename=file.filename or "fake.pdf",
                       upload_date=datetime.utcnow(), status=DocumentStatus.UPLOADED,
                       page_count=None)


@router.get("", response_model=DocumentList)
def list_documents(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentList:
    """List the current user's documents (FR-5, per-user isolation NFR-21).

    Requires authentication.  Even though real uploads arrive in Phase 2, the
    query is already scoped to ``current_user.id`` so two users can never see
    each other's documents (FR-3).

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session.
        current_user: The authenticated user whose documents are returned.

    Returns:
        A paginated list of the current user's documents (empty until Phase 2
        adds real uploads).
    """
    query = db.query(Document).filter(Document.user_id == current_user.id)
    total = query.count()
    items = query.order_by(Document.upload_date.desc()).offset(skip).limit(limit).all()
    return DocumentList(items=items, total=total)


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentDeleteResponse:
    """Delete an uploaded PDF (and all its derived data) (FR-23 — Phase 2).

    Requires authentication (NFR-20).  Phase 2 must additionally verify the
    document belongs to ``current_user`` (``Document.user_id == current_user.id``)
    before deleting, so one user cannot delete another user's document (FR-3).

    Args:
        document_id: ID of the document to delete.
        db: Database session (unused by the stub).
        current_user: The authenticated user (ownership check target).

    Returns:
        A stub deletion confirmation.
    """
    # TODO(Phase 2): verify ownership (Document.user_id == current_user.id),
    # remove the file from PDF File Storage, and cascade-delete
    # Document / Page / Chunk / Embedding rows (SQLite FK pragma is already ON).
    return DocumentDeleteResponse(deleted=True, document_id=document_id)