"""Document management API routes — real implementation (Phase 2).

Implements the "Backend API / Orchestrator" document endpoints (SDD §4):
upload, list, detail, and delete PDFs.  Every endpoint requires authentication
and scopes database queries to the current user (FR-3 / NFR-21).

See Phase 2 implementation instructions for full details on the upload flow,
validation, page-level ingestion orchestration, and aggregate status logic.

STANDING RULE (applies to every route file from Phase 1 onward): every
database query that reads or writes user-owned data (Document/Page/Chunk/
Query/Answer/Feedback/TokenUsage) MUST filter by the current user's id, e.g.
``db.query(Document).filter(Document.user_id == current_user.id, ...)``, so
FR-3 / NFR-21 (per-user isolation) is always enforced at the query layer.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.deps import get_current_user
from app.models.document import Document
from app.models.enums import DocumentStatus, PageStatus
from app.models.user import User
from app.schemas.document import (
    ApproveAllResponse,
    BatchUploadResponse,
    DocumentDeleteResponse,
    DocumentDetailOut,
    DocumentList,
    DocumentOut,
    DocumentUploadError,
    PageSummary,
)
from app.schemas.page import PageWithChunksOut
from app.services.ingestion_orchestrator import process_uploaded_pdf
from app.services.review_service import approve_all_pending
from app.utils.pdf_utils import (
    PdfProcessingError,
    PdfValidationError,
    ensure_storage_path,
    validate_pdf_file,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _compute_aggregate_status(doc: Document) -> DocumentStatus:
    """Compute a document's aggregate status from its pages (FR-22)."""
    if doc.status == DocumentStatus.DISCARDED:
        return DocumentStatus.DISCARDED
    if doc.status == DocumentStatus.FAILED:
        return DocumentStatus.FAILED

    pages = doc.pages or []
    if not pages:
        return DocumentStatus.UPLOADED

    page_statuses = {p.status for p in pages}

    if PageStatus.INITIAL_PROCESSING in page_statuses:
        return DocumentStatus.PROCESSING
    if PageStatus.LLM_REVIEW in page_statuses:
        return DocumentStatus.AWAITING_FEEDBACK
    if PageStatus.AWAITING_FEEDBACK in page_statuses:
        return DocumentStatus.AWAITING_FEEDBACK
    if all(p.status == PageStatus.APPROVED for p in pages):
        return DocumentStatus.READY

    return DocumentStatus.UPLOADED


def _document_to_out(doc: Document) -> DocumentOut:
    """Convert a Document ORM object to DocumentOut with aggregate status."""
    return DocumentOut(
        id=doc.id,
        user_id=doc.user_id,
        filename=doc.filename,
        upload_date=doc.upload_date,
        status=_compute_aggregate_status(doc),
        page_count=doc.page_count,
    )


def _get_user_document_or_404(
    db: Session, document_id: int, current_user: User
) -> Document:
    """Fetch a document by id, verifying ownership to current_user."""
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == current_user.id)
        .first()
    )
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found or not owned by you.",
        )
    return doc


# ---------------------------------------------------------------------------
# POST /documents — Upload one or more PDFs (FR-4, FR-5)
# ---------------------------------------------------------------------------


@router.post("", response_model=BatchUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_documents(
    files: list[UploadFile] = File(..., description="One or more PDF files to upload"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchUploadResponse:
    """Upload one or more PDF files for ingestion (FR-4, FR-5).

    Validates each file (type, size, magic bytes), saves it to disk, creates
    a Document row, and runs the per-page ingestion pipeline (synchronously).

    Per the OD-8 default, each upload creates an independent Document row even
    if the filename matches an existing document.

    A single bad file does not fail the whole batch (NFR-14 spirit).

    Args:
        files: One or more PDF files (multipart upload).
        db: Database session.
        current_user: The authenticated user.

    Returns:
        A BatchUploadResponse with successfully created documents and any
        per-file errors.
    """
    created_documents: list[Document] = []
    errors: list[DocumentUploadError] = []

    for uploaded_file in files:
        filename = uploaded_file.filename or "unnamed"

        try:
            file_bytes = uploaded_file.file.read()
            if not file_bytes:
                raise PdfValidationError("Empty file.")

            validate_pdf_file(filename, file_bytes)

            document = Document(
                user_id=current_user.id,
                filename=filename,
                status=DocumentStatus.UPLOADED,
            )
            db.add(document)
            db.flush()

            storage_path = ensure_storage_path(current_user.id, document.id)
            storage_path.write_bytes(file_bytes)
            logger.info("Saved '%s' for user %d at '%s'.", filename, current_user.id, storage_path)

            process_uploaded_pdf(db, document, str(storage_path))
            db.commit()
            created_documents.append(document)

            logger.info("Document %d ('%s') uploaded and processed.", document.id, filename)

        except (PdfValidationError, PdfProcessingError) as exc:
            db.rollback()
            logger.warning("Failed '%s': %s", filename, exc)
            errors.append(DocumentUploadError(filename=filename, error=str(exc)))
        except Exception as exc:
            db.rollback()
            logger.exception("Unexpected error '%s'.", filename)
            errors.append(
                DocumentUploadError(
                    filename=filename,
                    error=f"Internal server error: {exc}" if settings.DEBUG else "Internal server error.",
                )
            )
        finally:
            uploaded_file.file.close()

    return BatchUploadResponse(
        documents=[_document_to_out(d) for d in created_documents],
        errors=errors,
    )


@router.get("", response_model=DocumentList)
def list_documents(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentList:
    """List the current user's documents with aggregate status (FR-22).

    The returned status for each document is computed from the per-page
    statuses using _compute_aggregate_status (FR-22 precedence order).

    Args:
        skip: Pagination offset.
        limit: Pagination page size.
        db: Database session.
        current_user: The authenticated user.

    Returns:
        A paginated list of the current user's documents.
    """
    query = db.query(Document).filter(Document.user_id == current_user.id)
    total = query.count()
    items = query.order_by(Document.upload_date.desc()).offset(skip).limit(limit).all()

    return DocumentList(
        items=[_document_to_out(d) for d in items],
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentDetailOut:
    """Get full detail for a single document, including per-page statuses (FR-22).

    Args:
        document_id: ID of the document to retrieve.
        db: Database session.
        current_user: The authenticated user.

    Returns:
        Full document detail with nested page statuses.

    Raises:
        HTTPException: 404 if document not found or not owned by current user.
    """
    doc = _get_user_document_or_404(db, document_id, current_user)

    pages: list[PageSummary] = []
    for p in doc.pages or []:
        pages.append(
            PageSummary(
                id=p.id,
                page_number=p.page_number,
                status=p.status.value,
                extraction_method=p.extraction_method.value if p.extraction_method else None,
                quality_score=p.quality_score,
                review_round=p.review_round,
            )
        )

    return DocumentDetailOut(
        id=doc.id,
        user_id=doc.user_id,
        filename=doc.filename,
        upload_date=doc.upload_date,
        status=_compute_aggregate_status(doc),
        page_count=doc.page_count,
        pages=pages,
    )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentDeleteResponse:
    """Delete a previously uploaded document and all its derived data (FR-23).

    Removes:
        - The PDF file from disk (NFR-22).
        - All database rows (Document, Pages, Chunks cascade-deleted via FK).

    Args:
        document_id: ID of the document to delete.
        db: Database session.
        current_user: The authenticated user.

    Returns:
        A confirmation response with deleted=True.

    Raises:
        HTTPException: 404 if document not found or not owned by current user.
    """
    doc = _get_user_document_or_404(db, document_id, current_user)

    storage_path = ensure_storage_path(current_user.id, document_id)
    if storage_path.exists():
        try:
            storage_path.unlink()
            logger.info("Deleted PDF file at '%s'.", storage_path)
        except OSError as exc:
            logger.warning("Could not delete file '%s': %s", storage_path, exc)
    else:
        logger.warning("File '%s' for document %d was already missing.", storage_path, document_id)

    db.delete(doc)
    db.commit()

    logger.info("Document %d deleted for user %d.", document_id, current_user.id)
    return DocumentDeleteResponse(deleted=True, document_id=document_id)
# ────────────────────────────────────────────────────────────────────────
# GET /documents/{doc_id}/pages  — list pages with chunks for review
# ────────────────────────────────────────────────────────────────────────


@router.get("/{doc_id}/pages", response_model=list[PageWithChunksOut])
def list_document_pages(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PageWithChunksOut]:
    """List all pages of a document with their chunks for review (NFR-16, NFR-27)."""
    doc = _get_user_document_or_404(db, doc_id, current_user)
    return [
        PageWithChunksOut(
            id=p.id,
            document_id=p.document_id,
            page_number=p.page_number,
            status=p.status,
            extraction_method=p.extraction_method,
            quality_score=p.quality_score,
            review_round=p.review_round,
            review_note=p.review_note,
            updated_at=p.updated_at,
            chunks=p.chunks,
        )
        for p in (doc.pages or [])
    ]


# ────────────────────────────────────────────────────────────────────────
# POST /documents/{doc_id}/approve-all  — bulk approve all pending pages
# ────────────────────────────────────────────────────────────────────────


@router.post("/{doc_id}/approve-all", response_model=ApproveAllResponse)
def approve_all(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApproveAllResponse:
    """Approve every pending page of a document in a single step (FR-13, NFR-11, NFR-26)."""
    doc = _get_user_document_or_404(db, doc_id, current_user)
    count = approve_all_pending(doc, db)
    db.commit()
    message = (
        f"Approved {count} page(s)."
        if count > 0
        else "No pending pages to approve."
    )
    return ApproveAllResponse(
        document_id=doc_id,
        pages_approved=count,
        message=message,
    )