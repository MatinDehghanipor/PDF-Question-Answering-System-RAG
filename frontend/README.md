# PDF QA System — Client UI (Streamlit)

Multi-page web client for the **PDF Question-Answering System (RAG)** backend.
Users upload PDFs, review extracted content page by page, ask questions in RAG
or Raw mode, and view token-usage statistics.

Built with **Streamlit 1.50.0** (pinned for `starlette` compatibility with the
FastAPI backend — see below).

---

## Prerequisites

- **Python 3.10+** (tested on 3.11)
- The **backend** must be running (see *Quick Start* below)
- Installed frontend dependencies:
  ```powershell
  pip install -r frontend\requirements.txt
  ```
  (The backend also needs its own `requirements.txt` from `src/`.)

---

## Quick Start

### 1. Start the backend (in a terminal)

```powershell
cd src
copy .env.example .env        # first time: set JWT_SECRET_KEY at minimum
alembic upgrade head          # creates/updates the SQLite database
uvicorn app.main:app --reload
```

The backend listens on **http://127.0.0.1:8000** by default (health-check at
`GET /health` → `{"status": "ok"}`).

> **First startup:** the embedding model (`all-MiniLM-L6-v2`) is downloaded
> automatically (~80 MB) and may take 2–5 minutes.  The backend is ready when
> you see `Application startup complete.` in the log.

### 2. Start the frontend (in a **second** terminal)

```powershell
streamlit run frontend\streamlit_app.py
```

The frontend opens **http://localhost:8501** in your browser (the terminal
will show the URL).  If the backend is still loading, a red banner says
"Cannot reach the server" — refresh once the backend is ready.

---

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `API_BASE_URL` | `http://127.0.0.1:8000` | Backend server URL.  Set this in your shell before running Streamlit (e.g. `$env:API_BASE_URL="http://..."` on Windows). |

The frontend fetches tunable limits (`MIN_TOP_K`, `MAX_UPLOAD_SIZE_MB`, etc.)
from `GET /config/limits` on every page, so you never duplicate backend magic
numbers in the UI.

---

## Known Limitations

1. **Session token is lost on full page refresh.** Streamlit holds the JWT
   in memory (`st.session_state`).  A browser refresh destroys it — you must
   log in again.  This is expected Streamlit behaviour (Phase 12 spec §Pitfalls).

2. **No PDF-preview or image-serving endpoint.** The backend does not expose
   a route to download the original PDF file or extracted images
   (`ChunkOut.image_path` is a server filesystem path).  The review screen
   shows chunk text/captions and the server-side image path, but cannot
   render the original PDF or images inline.  (Not required by SRS §5.1.)

3. **Exclude checkbox — stored but not honoured by indexing.**  FR‑12 permits
   the user to exclude individual chunks from indexing.  The backend stores
   `excluded=True` on the chunk but **never converts it to
   `review_status=rejected`**, and the chunker's indexable-chunks query
   filters on `review_status` only.  As a result, excluded chunks are **still
   embedded and indexed**.  This is a backend gap (Phase 4/6).  The UI records
   the `excluded` flag correctly; the backend will honour it once the gap is
   fixed.

4. **Table chunk edits do not affect retrieval.**  When you edit a
   `chunk_type="table"` chunk in the review screen, the edit is sent via
   `PATCH /pages/chunks/{id}` → `chunk.text`.  However, the chunker reads
   `table_markdown` (not `text`) for embedding.  So table edits are persisted
   but **not reflected in RAG retrieval**.  Editing the text of a table is a
   cosmetic change only until the backend gap is fixed.

5. **No `/auth/me` endpoint.** The sidebar shows the identifier you typed
   at login (username **or** email), not the canonical username.
   (A `GET /auth/me` route would be needed to return the authenticated user's
   profile — potential future enhancement.)

6. **Automated UI tests not included in this phase.**  Full comprehensive
   testing and Docker packaging are addressed in Phase 13.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Red banner _"Cannot reach the server at …"_ | Backend not started, wrong port, or still loading the embedding model.  Start `uvicorn` from `src/` and wait for `Application startup complete.` |
| _"Your session expired"_ after every page refresh | **Normal.**  See limitation #1 above. |
| Upload fails with "_… exceeds the … MB limit_" | The backend rejected the file because it exceeds `MAX_UPLOAD_SIZE_MB` (default 100 MB).  The error text comes from the API verbatim. |
| Raw Mode returns _"Total file size … exceeds Raw Mode maximum"_ | The combined size of the selected documents exceeds `RAW_MODE_MAX_FILE_MB` or their total pages exceeds `RAW_MODE_MAX_PAGES`.  Select fewer / shorter files. |
| Review page shows _"All chunks excluded / no indexable chunks"_ after approving | The page may have only one chunk which was excluded (exclusion is stored, but the backend still indexes it — see limitation #3).  Try without excluding any chunk. |

---

## Screen Inventory

| URL / page | Purpose | Functional Req. | Non‑functional Req. |
|---|---|---|---|
| `streamlit_app.py` | Login / Register gate | FR‑1, FR‑2 | — |
| `pages/1_Documents.py` | Upload, list, delete PDFs | FR‑4, FR‑5, FR‑22, FR‑23 | NFR‑16 (status badges) |
| `pages/2_Review.py` | Per‑page review, edit chunks, approve / unsatisfied | FR‑11, FR‑12, FR‑13 | NFR‑3, NFR‑16, NFR‑19, NFR‑24, NFR‑26, NFR‑27 |
| `pages/3_Query.py` | RAG / Raw query, answer display, feedback | FR‑24, FR‑26, FR‑28, FR‑29, FR‑30, FR‑31, FR‑32, FR‑33 | NFR‑6, NFR‑17, NFR‑18, NFR‑28 |
| `pages/4_Usage.py` | Token‑usage statistics & drill‑down | FR‑34, FR‑35, FR‑15 (per‑page) | NFR‑30 |