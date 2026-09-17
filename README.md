# PDF QA System (RAG) — Backend

Multi-user PDF Question-Answering (RAG) system. Registered users upload PDFs
(~100 PDFs/user); each page goes through a page-level ingestion pipeline with
two rounds of human review, automatic OCR fallback, and LLM-based extraction
fallback, before chunking, embedding, and indexing. Users ask questions in
**RAG Mode** (top-k chunk retrieval + LLM answer) or **Raw Mode** (original PDF
sent to the LLM directly). Answers can be rated/commented, and every
LLM-consuming operation is token-tracked.

This repository currently implements **Phase 11 — Error Handling & Reliability**:
custom exception hierarchy (FR-36), centralized handlers (NFR-15), FR-37
reprocessing guards, per-page error isolation (NFR-14), and atomic approval +
indexing with Chroma rollback (NFR-12).

## Project Structure

```
src/
├── app/
│   ├── main.py                 # FastAPI app, CORS, routers, error handlers
│   ├── core/                   # config (NFR-25), database, logging
│   ├── models/                 # 9 SQLAlchemy entities from SDD §7
│   ├── schemas/                # Pydantic request/response schemas
│   ├── api/routes/             # auth, documents, pages, query, feedback, usage (stubs)
│   ├── services/               # placeholder modules per SDD §4 component
│   └── deps.py                 # shared FastAPI dependencies
├── alembic/                    # migrations (first: full schema creation)
├── tests/                      # pytest smoke tests
├── data/                       # gitignored: app.db, PDFs, vector store
├── alembic.ini
├── requirements.txt
├── .env.example
├── Dockerfile
└── README.md
```

## Getting Started

1. **Install system dependencies**:

   This project requires two system-level (non-Python) packages for PDF
   extraction (Phase 3):

   - **Ghostscript** (required by Camelot for table extraction):
     - *Windows:* Download from https://www.ghostscript.com/releases/gsdnld.html
       and ensure ``gswin64c`` (or ``gswin32c``) is on your ``PATH``.
     - *Linux:* ``sudo apt install ghostscript`` (or your distro's equivalent).
     - *macOS:* ``brew install ghostscript``.

   - **Tesseract OCR** (required by pytesseract for OCR fallback):
     - *Windows:* Download from https://github.com/UB-Mannheim/tesseract/wiki
       and ensure ``tesseract.exe`` is on your ``PATH``.
     - *Linux:* ``sudo apt install tesseract-ocr``.
     - *macOS:* ``brew install tesseract``.
     - For Persian/Arabic PDFs, also install the matching language pack
       (e.g., ``tesseract-ocr-fas`` on Linux/macOS) and pass
       ``lang="fas+eng"`` to the OCR function (see `ocr_extractor.py`).

   Verify both are installed:

   ```bash
   gswin64c --version   # Windows; or `gs --version` on Linux/macOS
   tesseract --version
   ```

2. **Install Python dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**:

   ```bash
   cp .env.example .env
   # edit .env as needed (all values documented; NFR-25)
   ```

3. **Create and apply the initial migration** (creates `data/app.db`
   with all 9 tables from SDD §7):

   ```bash
   alembic upgrade head
   ```

4. **Run the API**:

   ```bash
   uvicorn app.main:app --reload
   ```

5. **Verify**:

   - Health: `GET http://127.0.0.1:8000/health` → `{"status": "ok"}`
   - Swagger UI: `http://127.0.0.1:8000/docs`
   - Inspect the schema: `sqlite3 data/app.db ".schema"`

## Docker

```bash
docker build -t pdf-qa-system .
docker run -p 8000:8000 pdf-qa-system
```

## Running Tests

```bash
cd src
pytest tests/          # or: python -m pytest tests/ -v
```

The suite is self-contained.  `tests/conftest.py` points `DATABASE_URL`,
`FILE_STORAGE_PATH` and `VECTOR_STORE_PATH` at a temporary directory for the
whole session, creates the schema with `Base.metadata.create_all()`, and stubs
the embedding model — so tests need no `.env`, no Gemini API key and no model
download, and they leave the developer's `data/` tree (database, PDFs, vector
store) untouched.  The temporary directory is deleted at the end of the run.

Since those paths are absolute, the tests can be run from anywhere:

```bash
python -m pytest src/tests/ -v
```

## Configuration (NFR-25)

Every tunable value (chunk size/top-k, quality threshold, embedding model,
LLM models, Raw Mode limits, storage paths) lives in `app/core/config.py`
and is overridable via environment variables / `.env` — no code changes
needed.

## Phase Log

- **Phase 0 (complete)** — Project scaffolding & full system skeleton:
  - Full SDD §7 database schema (9 tables, enums, FKs, indexes) via SQLAlchemy
    + Alembic migration.
  - Centralized `Settings` (NFR-25) with all tunables defined up front.
  - Entire final API surface mounted as stubs (auth, documents, pages/review,
    query, feedback, usage) with accurate request/response shapes.
  - Empty service modules for every SDD §4 component.
  - Global error/404 handlers (FR-36 foundation), storage-path startup checks,
    CORS, `/health`.
  - Dockerfile, .env.example, .gitignore, pytest smoke tests.

*Later phases append one bullet per completed phase here.*

- **Phase 3 (complete)** — Native Extraction, Quality Scoring & OCR Fallback:
  - Real native extractor using PyMuPDF (text blocks, Camelot tables, embedded
    images with captions).
  - Heuristic quality scorer (OD-3 default: char density + garbled ratio).
  - Real OCR extractor using Tesseract (300 DPI rendering, text + tables +
    images).
  - Shared `ExtractionResult` type (TextBlock, TableBlock, ImageBlock) used
    by all extractors (SDD §2.2).
  - Proximity-based image caption matcher (OD-4 default, no LLM).
  - Per-block chunk creation in ingestion orchestrator.
  - Error handling per NFR-14: single-page failures never abort the document.
  - `ocr_failed` extraction method for Tesseract-unavailable pages.
  - Updated dependencies (camelot-py, pytesseract, pandas, tabulate).
  - System dependency docs (Ghostscript, Tesseract).

- **Phase 11 (complete)** — Error Handling & Reliability:
  - Custom exception hierarchy (`AppException`, `NotFoundError`, `ConflictError`,
    `ValidationError`, `UpstreamServiceError`) in `app/core/exceptions.py`.
  - Centralized exception handler registered in `app/main.py` producing consistent
    JSON `{"error": "...", "detail": "..."}` responses (FR-36, NFR-15).
  - All route files (`pages.py`, `documents.py`, `queries.py`, `feedback.py`,
    `usage.py`) migrated from ad-hoc `HTTPException` raises to the new hierarchy.
  - FR-37 reprocessing guards (defense-in-depth added to `native_extractor.py`,
    `ocr_extractor.py`, `quality_scorer.py`, `chunker.py`, `embedding_service.py`).
  - Per-page error isolation reinforced in `process_uploaded_pdf()`: a single
    page exception now catches, logs, and continues — if all pages fail the
    document is set to `FAILED` status (NFR-14).
  - Atomicity fix in `_index_page_and_update_status()`: Chroma vectors are
    removed if the DB status update fails after a successful upsert (NFR-12).
  - Integration tests in `test_reliability.py` covering exception serialisation,
    per-page isolation, and indexing rollback.

## Known Limitations

1. **In-memory FR-37 guards are ephemeral.** The reprocessing guards in
   `native_extractor._processed_native`, `ocr_extractor._processed_ocr`,
   `quality_scorer._processed_scores`, and `embedding_service._embedded_hashes`
   use module-level sets that reset on process restart.  They are defense-in-depth
   only; the authoritative gatekeeper is the page/document status machine in the
   database.

2. **Chroma vectors may outlive a rolled-back transaction in edge cases.**
   The atomicity fix in `_index_page_and_update_status()` catches DB failures
   after a successful Chroma upsert and attempts to clean up the vectors.  If
   the cleanup itself fails (e.g. Chroma is unreachable), the orphaned vectors
   remain until the next successful re-indexing of the same document overwrites
   them.  This is logged at ERROR level.

3. **Exception status‑code remapping.** Some HTTPException calls that used
   status codes not present in the custom hierarchy (e.g. 413 from OD‑7 limit
   checks) have been mapped to `ValidationError` (422).  This changes the status
   code returned to clients for those specific error cases.  If backwards
   compatibility is required, extend the hierarchy with additional status codes.

4. **Deps.py 401 raises remain as HTTPException.** The JWT authentication
   dependency in `deps.py` must raise `HTTPException(401)` with a
   `WWW-Authenticate: Bearer` header so that FastAPI's `OAuth2PasswordBearer`
   contract is satisfied.  These are left as-is — they are not part of the
   custom hierarchy by design.