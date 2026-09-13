"""FastAPI application entry point.

Creates the FastAPI app for the "Backend API / Orchestrator" component
(SDD §4): mounts every router, configures permissive CORS for development,
installs global error/404 handlers (foundation for FR-36), and validates at
startup that the database and file-storage paths are usable.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import auth, documents, feedback, pages, queries, usage
from app.core.config import settings
from app.core.database import engine
from app.core.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def _validate_storage_paths() -> None:
    """Fail fast at startup if critical data paths are unusable.

    Realizes the Phase-0 error-handling requirement: validates that the
    SQLite database directory and the PDF file-storage directory exist or
    can be created, logging a clear message before exiting otherwise.

    Raises:
        RuntimeError: If a required path cannot be created.
    """
    # sqlite:///./data/app.db -> ./data
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite"):
        db_path = Path(db_url.replace("sqlite:///", ""))
        db_dir = db_path.parent if db_path.suffix else db_path
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                f"Cannot create database directory '{db_dir}' for DATABASE_URL "
                f"'{db_url}': {exc}"
            ) from exc

    storage = Path(settings.FILE_STORAGE_PATH)
    try:
        storage.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Cannot create FILE_STORAGE_PATH '{storage}': {exc}"
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: validate storage paths and check DB connectivity."""
    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.APP_ENV)
    _validate_storage_paths()
    try:
        # Lightweight connectivity check: inspect() connects lazily, so run a
        # trivial SELECT to fail fast if the DB file cannot be opened.
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Cannot connect to database at DATABASE_URL '{settings.DATABASE_URL}': {exc}"
        ) from exc
    logger.info("Storage and database checks passed.")
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description=(
        "Multi-user PDF Question-Answering (RAG) system backend.  Phase 0 "
        "skeleton: all endpoints are stubs returning clearly-marked fake data "
        "until their owning phase implements real logic."
    ),
    lifespan=lifespan  # type: ignore[attr-defined]
)


# Permissive CORS for development (SDD §4 Client UI will be served from a
# different origin in Phase 12; tighten before production).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Global exception handling (foundation for FR-36) -----------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a sanitized 500 JSON body instead of leaking a traceback.

    Realizes FR-36 (error handling): logs the full traceback server-side and
    returns ``{"error": "internal_server_error", "detail": ...}`` to clients.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": "An unexpected error occurred."},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Return a consistent JSON body for HTTP exceptions (404 unknown routes etc.)."""
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "detail": f"Route '{request.url.path}' not found.",
            },
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "detail": str(exc.detail)},
    )


# --- Health check -----------------------------------------------------------
@app.get("/health", tags=["health"], summary="Liveness check")
def health() -> dict[str, str]:
    """Return a 200 OK payload confirming the API is alive."""
    return {"status": "ok"}


# --- Routers -----------------------------------------------------------------
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(pages.router)
app.include_router(queries.router)
app.include_router(feedback.router)
app.include_router(usage.router)