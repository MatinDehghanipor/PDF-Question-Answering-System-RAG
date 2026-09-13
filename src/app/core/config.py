"""Central application configuration for the PDF QA system.

This module implements the configuration layer of the backend (SDD §3,
SDD §7).  It realizes NFR-25 ("Chunk size, top-k value, the quality-score
metric and its threshold, the embedding model, and the LLM(s) used for
answering and for LLM Review shall all be configurable without code changes")
by loading every tunable value from environment variables / `.env` via
Pydantic's `BaseSettings`.

Every future phase should reference ``settings.X`` here rather than inventing
new ad-hoc settings, so the whole system stays configurable from one place.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is two levels above this file (app/core/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables / `.env`.

    Realizes NFR-25: all quality, retrieval, embedding, and LLM parameters are
    configurable without code changes.
    """

    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General application ---
    APP_NAME: str = "PDF QA System"
    APP_ENV: str = "development"
    DEBUG: bool = False

    # --- Database ---
    # SQLite is the Phase-0 store (SDD §3); PostgreSQL is a future migration path.
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # --- Auth (used starting Phase 1 — JWT) ---
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # --- File upload (used starting Phase 2) ---
    MAX_UPLOAD_SIZE_MB: int = 100

    # --- Chunking (used starting Phase 6) ---
    # [WORKING DEFAULT — OD-1]: chunk size 500 tokens with 50-token overlap.
    CHUNK_SIZE_TOKENS: int = 500
    CHUNK_OVERLAP_TOKENS: int = 50

    # --- Retrieval / top-k (used starting Phase 7) ---
    # [WORKING DEFAULT — OD-2]: default top-k = 5, clamped to [1, 20].
    DEFAULT_TOP_K: int = 5
    MIN_TOP_K: int = 1
    MAX_TOP_K: int = 20

    # --- Quality score (used starting Phase 3) ---
    # [WORKING DEFAULT — OD-3]: pages with quality score >= 0.6 are accepted.
    QUALITY_SCORE_THRESHOLD: float = 0.6

    # --- Embeddings / vector store (used starting Phase 6) ---
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    VECTOR_STORE_PATH: str = "./data/vector_store"

    # --- LLMs (used starting Phases 5, 7, 8) ---
    # [WORKING DEFAULT — OD-12]: same model for answering and review.
    LLM_ANSWER_MODEL: str = "gemini-2.0-flash"
    LLM_REVIEW_MODEL: str = "gemini-2.0-flash"

    # --- Raw Mode (used starting Phase 8) ---
    # [WORKING DEFAULT — OD-7]: max 50 MB per PDF and max 100 pages in Raw Mode.
    RAW_MODE_MAX_FILE_MB: int = 50
    RAW_MODE_MAX_PAGES: int = 100

    # --- File storage ---
    FILE_STORAGE_PATH: str = "./data/pdfs"


settings = Settings()