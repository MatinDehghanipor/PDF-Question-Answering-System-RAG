"""Read-only configuration endpoint for the frontend UI (Phase 12).

Exposes tunable limits so the Streamlit client can display correct
constraints (MIN_TOP_K, MAX_TOP_K, etc.) without duplicating magic
numbers from ``app.core.config``.
"""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/limits")
def get_limits() -> dict:
    """Return read-only backend limits for the frontend UI.

    Fields:
        MIN_TOP_K: Minimum allowed top-k value.
        MAX_TOP_K: Maximum allowed top-k value.
        DEFAULT_TOP_K: Default top-k value.
        MAX_UPLOAD_SIZE_MB: Maximum per-file upload size.
        RAW_MODE_MAX_FILE_MB: Maximum total file size for Raw Mode.
        RAW_MODE_MAX_PAGES: Maximum total page count for Raw Mode.
    """
    return {
        "MIN_TOP_K": settings.MIN_TOP_K,
        "MAX_TOP_K": settings.MAX_TOP_K,
        "DEFAULT_TOP_K": settings.DEFAULT_TOP_K,
        "MAX_UPLOAD_SIZE_MB": settings.MAX_UPLOAD_SIZE_MB,
        "RAW_MODE_MAX_FILE_MB": settings.RAW_MODE_MAX_FILE_MB,
        "RAW_MODE_MAX_PAGES": settings.RAW_MODE_MAX_PAGES,
    }