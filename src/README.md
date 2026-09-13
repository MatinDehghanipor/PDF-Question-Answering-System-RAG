# PDF QA System (RAG) — Backend

Multi-user PDF Question-Answering (RAG) system. Registered users upload PDFs
(~100 PDFs/user); each page goes through a page-level ingestion pipeline with
two rounds of human review, automatic OCR fallback, and LLM-based extraction
fallback, before chunking, embedding, and indexing. Users ask questions in
**RAG Mode** (top-k chunk retrieval + LLM answer) or **Raw Mode** (original PDF
sent to the LLM directly). Answers can be rated/commented, and every
LLM-consuming operation is token-tracked.

This repository currently implements **Phase 0 — Project Scaffolding & Full
System Skeleton**: a runnable backend with the complete final API surface
(stubbed), the full SDD §7 database schema, centralized configuration
(NFR-25), and empty service modules for every SDD §4 component.

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

1. **Install dependencies** (Python 3.11+ recommended):

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
pytest tests/
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