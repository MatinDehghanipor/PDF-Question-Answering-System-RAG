"""Phase 12 page: per-document page-by-page review (FR-11/12/13).

Displays NFR-16/19/24/26/27/3 visual cues: per-page status (NFR-16),
review round and extraction method (NFR-19), LLM Review badge (NFR-24),
chunk provenance (NFR-27), Approve All (NFR-26), and LLM-in-progress
caption (NFR-3).

Pitfall avoided (Phase 12 spec §LIKELY BUGS / PITFALLS):
    #4: the "Approve" button always PATCHes any pending chunk edits still
    held in widget state BEFORE calling the review endpoint, so unsaved
    text is never silently discarded.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
import api_client as api
import ui_helpers as uh
from collections import Counter

st.set_page_config(page_title="Page Review", page_icon="🔍")
st.title("🔍 Page Review")

uh.require_login()
_TOKEN = st.session_state["token"]
uh.sidebar_identity()
uh.show_flash()

_SZ = st.session_state

# ──────────────────────────────────────────────────────────────────────
# Document selector (if no document was pre-selected from 1_Documents.py)
# ──────────────────────────────────────────────────────────────────────

doc_id: int | None = _SZ.get("selected_document_id")

if not doc_id:
    docs_resp = uh.handle_api_call(api.list_documents, _TOKEN)
    if docs_resp is None or not docs_resp.get("items"):
        st.info("No documents available — upload one first.")
        st.stop()
    doc_id = st.selectbox(
        "Select a document to review",
        options=[d["id"] for d in docs_resp["items"]],
        format_func=lambda i: next(
            (d["filename"] for d in docs_resp["items"] if d["id"] == i), f"#{i}"
        ),
    )
    _SZ["selected_document_id"] = doc_id
    st.rerun()

# ──────────────────────────────────────────────────────────────────────
# Cache helpers (pages list is fetched once per document and only
# refetched after a mutation — Phase 12 pitfall #3).
# ──────────────────────────────────────────────────────────────────────

PAGE_CACHE_KEY = f"_review_pages_{doc_id}"


def _fetch_pages() -> list[dict]:
    """GET /documents/{doc_id}/pages and cache in session_state."""
    resp = uh.handle_api_call(api.get_document_pages, _TOKEN, doc_id)
    if resp is not None:
        _SZ[PAGE_CACHE_KEY] = resp
    return _SZ.get(PAGE_CACHE_KEY, [])


def _invalidate_cache() -> None:
    """Remove the cached page list so the next render refetches."""
    _SZ.pop(PAGE_CACHE_KEY, None)


pages = _SZ.get(PAGE_CACHE_KEY) or _fetch_pages()

if not pages:
    st.info("This document has no pages (or the backend returned an empty list).")
    st.stop()

# ──────────────────────────────────────────────────────────────────────
# Page-level edit saver — patch pending chunk edits before approving.
# Phase 12 pitfall #4: ensuring user edits are not silently discarded.
# ──────────────────────────────────────────────────────────────────────


def _save_pending_edits(page: dict) -> None:
    """PATCH any chunk whose text_area / exclude widget differs from its DB state."""
    for chunk in page.get("chunks", []):
        cid = chunk["id"]
        edits: dict = {}
        # text: only text/table chunks have an editable text_area
        if chunk.get("chunk_type") in ("text", "table"):
            wv = _SZ.get(f"chunk_text_{cid}")
            if wv is not None and wv != uh.chunk_editable_text(chunk):
                edits["text"] = wv
        # excluded: all chunk types have a checkbox
        ev = _SZ.get(f"chunk_excl_{cid}")
        if ev is not None and ev != chunk.get("excluded"):
            edits["excluded"] = ev
        if edits:
            uh.handle_api_call(api.patch_chunk, _TOKEN, cid, **edits)


# ──────────────────────────────────────────────────────────────────────
# Approve All (FR-13 / NFR-26) — batch approve every pending page.
# ──────────────────────────────────────────────────────────────────────


def _do_approve_all() -> None:
    """POST /documents/{doc_id}/approve-all with confirmation."""
    resp = uh.handle_api_call(api.approve_all, _TOKEN, doc_id)
    if resp is not None:
        msg = resp.get("message", "")
        st.toast(f"✅ {msg}", icon="📄")
        _invalidate_cache()
        st.rerun()


# ──────────────────────────────────────────────────────────────────────
# Page-level approve / mark-unsatisfied
# ──────────────────────────────────────────────────────────────────────


def _do_approve_page(page: dict) -> None:
    """Save pending edits for this page, then approve (FR-12)."""
    _save_pending_edits(page)
    resp = uh.handle_api_call(api.submit_page_review, _TOKEN, page["id"], "approved")
    if resp is not None:
        st.toast(f"Page {page['page_number']} approved.", icon="✅")
        _invalidate_cache()
        st.rerun()


def _do_mark_unsatisfied(page_id: int, note: str | None = None) -> None:
    """Mark a page unsatisfactory (Round 1 -> LLM Review; Round 2 -> discard)."""
    resp = uh.handle_api_call(api.submit_page_review, _TOKEN, page_id, "unsatisfied", note)
    if resp is not None:
        next_status = resp.get("next_status", "")
        if next_status == "discarded":
            st.toast("⚠️ This page was in Round 2 — the document has been discarded.", icon="🗑️")
        else:
            st.toast("Page sent to LLM Review.", icon="🤖")
        _invalidate_cache()
        st.rerun()
# ──────────────────────────────────────────────────────────────────────
# Document header
# ──────────────────────────────────────────────────────────────────────

if pages:
    doc_filename = pages[0].get("document_filename", f"Document #{doc_id}")
    st.subheader(doc_filename)
    st.caption(f"**{len(pages)} page(s)** total · Select a document from the docs page.")

    # Compute counts per status for the header (NFR-16 aggregate)

    status_counts = Counter(p.get("status", "") for p in pages)
    status_display = ", ".join(
        f"{uh.status_badge(s, 'page')}: {c}" for s, c in sorted(status_counts.items())
    )
    st.write(status_display)

    # "Approve All" button (FR-13 / NFR-26)
    pending_count = sum(1 for p in pages if p.get("status") == "awaiting_feedback")
    if pending_count > 0:
        if st.button(
            f"✅ Approve All ({pending_count} pending)",
            type="primary", use_container_width=True, key="approve_all_btn",
        ):
            _do_approve_all()
    else:
        st.caption("No pages awaiting feedback — all approved or already in review.")

    if st.button("🔄 Refresh pages", key="refresh_pages"):
        _invalidate_cache()
        st.rerun()

    st.divider()

# ──────────────────────────────────────────────────────────────────────
# Per-page review (each page in an expander)
# ──────────────────────────────────────────────────────────────────────

for page in sorted(pages, key=lambda p: p.get("page_number", 0)):
    pnum = page.get("page_number", "?")
    pstatus = page.get("status", "?")
    page_id = page.get("id")
    chunks = page.get("chunks", [])
    is_await = uh.is_awaiting_llm_review(page)
    is_llm = uh.is_llm_extracted(page)

    # ── expander header ──
    badge = uh.status_badge(pstatus)
    expander_title = f"**Page {pnum}** — {badge}"
    with st.expander(expander_title, expanded=(pstatus == "awaiting_feedback")):
        # ── NFR-19: review round + method ──
        st.caption(uh.round_label(page))

        # ── NFR-19: quality score trigger caption ──
        qc = uh.quality_caption(page)
        if qc:
            st.caption(qc)

        # ── NFR-24: LLM Review badge ──
        if is_llm:
            st.warning("⚠️ This page's content was extracted via **LLM Review** (FR-14).")

        # ── NFR-3: LLM-in-progress spinner ──
        if is_await:
            st.info(
                "🤖 This page is being re-extracted by an LLM — this may take longer. "
                "Refresh the page list above to see the updated content."
            )
            continue  # no chunk editing while in LLM Review

        # ── review note (OD-14) ──
        if page.get("review_note"):
            st.info(f"📝 Reviewer note: *{page['review_note']}*")

        if pstatus in ("approved", "discarded"):
            st.stop()
# ── Chunks ──
        for chunk in sorted(chunks, key=lambda c: c.get("reading_order", 0)):
            cid = chunk["id"]
            chunk_type = chunk.get("chunk_type", "?")
            editable = chunk_type in ("text", "table")

            # NFR-27: source caption — page, type, order, round, method, review state
            st.markdown(f"*{uh.chunk_source_caption(page, chunk)}*")

            # Editable text for text/table chunks
            if editable:
                current_text = uh.chunk_editable_text(chunk)
                st.text_area(
                    "Content",
                    value=current_text,
                    key=f"chunk_text_{cid}",
                    height=100,
                    help="Edit the text here.  Changes are sent when you click **Approve**.",
                )
            elif chunk_type == "image":
                caption = chunk.get("image_caption") or "*no caption*"
                img_path = chunk.get("image_path") or "*not available*"
                st.info(f"🖼️ **Caption:** {caption}")
                st.caption(f"Image file (server path): `{img_path}`")
            else:
                st.caption(f"Chunk type `{chunk_type}` (read-only)")

            # Exclude checkbox
            st.checkbox(
                "Exclude this chunk from indexing",
                value=chunk.get("excluded", False),
                key=f"chunk_excl_{cid}",
                help=(
                    "Excluded chunks are recorded but the backend currently still "
                    "indexes them — see README known-limitations.  You can still use this "
                    "checkbox now; the backend will honour it once the gap is fixed."
                ),
            )
            st.divider()

        # Unsatisfied note (OD-14)
        st.text_area(
            "Note (optional — passed to LLM Review)",
            key=f"review_note_{page_id}",
            help="FR-14: if in Round 1, this note is passed to the vision-LLM as extra guidance.",
        )

        # ── Approve / Mark Unsatisfied ──
        col_ok, col_unsat = st.columns(2)
        with col_ok:
            if st.button("✅ Approve", key=f"appr_{page_id}", use_container_width=True):
                _do_approve_page(page)
        with col_unsat:
            if st.button("❌ Mark Unsatisfied", key=f"unsat_{page_id}", use_container_width=True):
                note = _SZ.get(f"review_note_{page_id}", "")
                _do_mark_unsatisfied(page_id, note or None)

# ── Status legend ──
with st.expander("Page status legend", expanded=False):
    st.write(
        """- **⏳ Initial Processing** — page is being extracted natively.
- **📝 Awaiting Feedback** — extraction complete; you can review, edit, and approve.
- **🤖 LLM Review** — content was unsatisfactory in Round 1; a vision-LLM is re-extracting.
- **✅ Approved** — content accepted and indexed; visible in RAG queries.
- **🗑️ Discarded** — document was removed after a Round‑2 rejection."""
    )

st.caption(
    f"Backend: `{api.API_BASE}`  |  "
    "A full page refresh signs you out (the token is in-memory)."
)