"""Phase 12 page: document upload, listing, and deletion (FR-4/5/22/23).

Called after successful authentication from ``streamlit_app.py``.  Every access
path requires a valid JWT; expired/missing tokens redirect back to login.

Backend contract (all routes require ``Authorization: Bearer <token>``):
    * ``POST /documents`` (multipart, field ``files``) → ``{documents:[DocumentOut],
      errors:[{filename,error}]}`` (FR-4, FR-5).  Validation errors per file
      (413/422) are surfaced verbatim in the ``errors`` list.
    * ``GET /documents`` → ``{items:[{id,filename,upload_date,status,page_count}],
      total}`` — aggregate status per document (FR-22).
    * ``DELETE /documents/{id}`` → ``{deleted:true,document_id}`` (FR-23).
    * ``POST /documents/{id}/approve-all`` → ``{pages_approved,message}``.
    * ``GET /config/limits`` → ``{MAX_UPLOAD_SIZE_MB, ...}``.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # frontend/ on sys.path

import streamlit as st
import api_client as api
import ui_helpers as uh  # noqa: E402 (path already fixed above)

st.set_page_config(page_title="Documents", page_icon="📄")
st.title("📄 Documents")

uh.require_login()
_TOKEN = st.session_state["token"]
uh.sidebar_identity()
uh.show_flash()

limits = uh.load_limits()
max_upload_mb = limits.get("MAX_UPLOAD_SIZE_MB", 100)

_SZ = st.session_state

# ──────────────────────────────────────────────────────────────────────
# Cache helpers (protect against Streamlit's top-to-bottom reruns)
# ──────────────────────────────────────────────────────────────────────


def _refresh_doc_list() -> None:
    """Fetch ``GET /documents`` and cache the result in session_state."""
    docs = uh.handle_api_call(api.list_documents, _TOKEN)
    if docs is not None and isinstance(docs, dict):
        _SZ["documents"] = docs.get("items", [])
    else:
        _SZ["documents"] = []


def _init_session() -> None:
    """Populate session keys that survive across reruns."""
    if "documents" not in _SZ:
        _refresh_doc_list()
    if "upload_results" not in _SZ:
        _SZ["upload_results"] = None


_init_session()


# ──────────────────────────────────────────────────────────────────────
# Upload section (FR-4, FR-5)
# ──────────────────────────────────────────────────────────────────────

st.subheader("Upload PDFs")
st.caption(f"Maximum file size per PDF: **{max_upload_mb} MB** (set by the backend; FR-5).")

uploaded_files = st.file_uploader(
    "Choose one or more PDF files",
    type="pdf",
    accept_multiple_files=True,
    help=(
        f"PDF files only.  Each file must be under {max_upload_mb} MB. "
        "You can select multiple files at once."
    ),
)

if st.button("📤 Upload", type="primary", use_container_width=True, key="upload_btn"):
    if not uploaded_files:
        st.warning("Select at least one PDF file first.")
    else:
        # Check file sizes client-side before sending
        oversized = [f.name for f in uploaded_files if f.size > max_upload_mb * 1024 * 1024]
        if oversized:
            st.error(
                f"The following files exceed the {max_upload_mb} MB limit: "
                f"{', '.join(oversized)}.  Upload not sent — please check and retry."
            )
        else:
            files_data = [(f.name, f.read()) for f in uploaded_files]
            result = uh.handle_api_call(api.upload_documents_bytes, _TOKEN, files_data)
            if result is not None:
                _SZ["upload_results"] = result
                _SZ["last_upload_names"] = ", ".join(f[0] for f in files_data)
                _refresh_doc_list()

# Show upload results (one-shot, then cleared)
upload_result = _SZ.pop("upload_results", None)
if upload_result:
    last_names = _SZ.pop("last_upload_names", "")
    created = upload_result.get("documents", [])
    errors = upload_result.get("errors", [])
    if created:
        st.toast(f"✅ {len(created)} document(s) uploaded successfully.", icon="📄")
        for doc in created:
            st.write(f"- **{doc['filename']}** — status: {uh.status_badge(doc['status'], 'document')}")
    if errors:
        st.error(f"Errors during upload of {last_names or 'some files'}:")
        for err in errors:
            st.write(f"  ❌ **{err['filename']}**: {err['error']}")
        st.caption(
            "Large files or OD-7 Raw-Mode limit violations are reported by the "
            "backend directly — the error text above comes from the API verbatim."
        )
# ──────────────────────────────────────────────────────────────────────
# Document list (FR-22, FR-23, NFR-16)
# ──────────────────────────────────────────────────────────────────────

st.subheader("Your PDFs")
st.caption(
    "Aggregate status is computed from per-page statuses. "
    f"See **{uh.DOCUMENTS_PAGE}** → {uh.REVIEW_PAGE} for page-level detail."
)

col_refresh, *rest = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh", key="refresh_docs"):
        _refresh_doc_list()

docs = _SZ.get("documents", [])
if not docs:
    st.info("No documents yet — upload one above!")
    st.stop()
# Render a table with one row per document
for doc in docs:
    did = doc.get("id")
    filename = doc.get("filename", "?")
    status = uh.status_badge(doc.get("status"), "document")
    page_count = doc.get("page_count") or "?"
    upload_date = doc.get("upload_date", "").split("T")[0] if doc.get("upload_date") else "?"
    discarded = doc.get("status") == "discarded"
    failed = doc.get("status") == "failed"

    cols = st.columns([0.3, 2, 0.6, 0.6, 0.5, 0.5, 0.5])
    cols[0].write(f"**#{did}**")
    cols[1].write(filename)
    cols[2].write(upload_date)
    cols[3].write(f"{page_count} pages")
    cols[4].markdown(status)
# Review button: navigates to the review page for this document
    with cols[5]:
        if st.button("Review", key=f"review_{did}", use_container_width=True,
                     disabled=discarded or failed):
            _SZ["selected_document_id"] = did
            st.switch_page(uh.REVIEW_PAGE)

    # Delete with two-step confirmation (Phase 12 spec: confirmation dialog)
    with cols[6]:
        if st.button("Delete", key=f"del_{did}", use_container_width=True,
                     disabled=discarded or failed):
            _SZ[f"confirm_del_{did}"] = True

    # Show confirmation only for the row where Delete was just clicked
    if _SZ.get(f"confirm_del_{did}"):
        st.warning(f"Delete **{filename}** (id={did})? This action cannot be undone.")
        col_conf, col_cancel = st.columns([1, 1])
        with col_conf:
            if st.button("Yes, delete", key=f"confirm_yes_{did}", type="primary",
                         use_container_width=True):
                result = uh.handle_api_call(api.delete_document, _TOKEN, did)
                if result is not None:
                    st.toast(f"Deleted: {filename}", icon="🗑️")
                    _SZ[f"confirm_del_{did}"] = False
                    _refresh_doc_list()
                    st.rerun()
        with col_cancel:
            if st.button("Cancel", key=f"confirm_no_{did}", use_container_width=True):
                _SZ[f"confirm_del_{did}"] = False
                st.rerun()

    st.divider()

# ── Status legend (NFR-16 reference) ──────────────────────────────
with st.expander("Status legend", expanded=False):
    for s, label in uh.DOCUMENT_STATUS_LABELS.items():
        st.write(f"**{label}**")
        st.caption(
            {
                "uploaded": "PDF received; pages being processed.",
                "processing": "At least one page is still being extracted / scored.",
                "awaiting_feedback": "At least one page is waiting for your review.",
                "ready": "All pages approved and indexed — you can ask questions about this document.",
                "discarded": "Document was discarded after a Round‑2 rejection of its content.",
                "failed": "All pages of this document failed extraction (no usable content produced).",
            }.get(s, "")
        )

st.caption(
    f"Backend: `{api.API_BASE}` | "
    "A full page refresh signs you out (the session token is in-memory)."
)