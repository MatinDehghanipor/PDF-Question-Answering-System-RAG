"""Phase 12 page: query in RAG or Raw mode (FR-24/26/28/29/30/31/32/33).

Displays NFR-6 (Raw Mode caption), NFR-17 (source references),
NFR-18 (mode badge before submit and on every answer), and NFR-28
(feedback optional, never blocks).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
import api_client as api
import ui_helpers as uh

st.set_page_config(page_title="Ask a Question", page_icon="❓")
st.title("❓ Ask a Question")

uh.require_login()
uh.sidebar_identity()
uh.show_flash()

_SZ = st.session_state
limits = uh.load_limits()
min_k = limits.get("MIN_TOP_K", 1)
max_k = limits.get("MAX_TOP_K", 20)
default_k = limits.get("DEFAULT_TOP_K", 5)
raw_max_pages = limits.get("RAW_MODE_MAX_PAGES", 100)
raw_max_mb = limits.get("RAW_MODE_MAX_FILE_MB", 50)

if "query_history" not in _SZ:
    _SZ["query_history"] = []

# ──────────────────────────────────────────────────────────────────────
# Mode selection (NFR-18: explicitly label the active mode before submit)
# ──────────────────────────────────────────────────────────────────────

mode = st.radio(
    "Query mode",
    options=["rag", "raw"],
    format_func=lambda m: {"rag": "📖 RAG — answered from indexed content (faster, cheaper)",
                           "raw": "📁 Raw Mode — original PDF(s) sent to the LLM directly"}[m],
    index=0,
    horizontal=True,
    help=(
        "RAG: retrieves the most relevant chunks from your approved documents and uses "
        "them as context for the LLM.  Raw: sends the entire selected PDF(s) to the LLM "
        "with no preprocessing."
    ),
)

# ──────────────────────────────────────────────────────────────────────
# RAG mode controls
# ──────────────────────────────────────────────────────────────────────

if mode == "rag":
    st.caption("**Active mode: 📖 RAG** — answer grounded in your approved, indexed documents (NFR-18).")
    k_value = st.slider(
        "How many chunks to retrieve (top‑k)",
        min_value=min_k,
        max_value=max_k,
        value=default_k,
        help=f"The number of most‑relevant chunks fed to the LLM.  Configurable range [{min_k}–{max_k}].",
    )
    selected_doc_ids = None  # not used in RAG mode

# ──────────────────────────────────────────────────────────────────────
# Raw Mode controls (FR-28: document multiselect, NFR-6 warning)
# ──────────────────────────────────────────────────────────────────────

else:
    st.caption(
        "**Active mode: 📁 Raw Mode** — the *original* PDF file(s) are sent to the LLM "
        "without being chunked or indexed (FR-28).  "
        "⚠️ Raw Mode may take **longer** and cost **more tokens** than RAG Mode (NFR-6)."
    )
    docs_resp = uh.handle_api_call(api.list_documents)
    ready_docs = [d for d in (docs_resp.get("items") if docs_resp else []) if d.get("status") == "ready"]
    if not ready_docs:
        st.warning(
            "You have no documents with status **Ready**.  "
            "Only fully‑approved, indexed documents can be queried in Raw Mode."
        )
        selected_doc_ids = None
    else:
        selected_doc_ids = st.multiselect(
            "Select document(s) to send to the LLM",
            options=[d["id"] for d in ready_docs],
            format_func=lambda i: next(d["filename"] for d in ready_docs if d["id"] == i),
            default=None,
            help=(
                f"Raw Mode limit: up to **{raw_max_pages} pages** and **{raw_max_mb} MB** total "
                f"(FR-5 / OD-7).  Over‑sized selections are rejected by the backend with a "
                "clear error."
            ),
        )

# ──────────────────────────────────────────────────────────────────────
# Question input
# ──────────────────────────────────────────────────────────────────────

question = st.text_area(
    "Your question",
    key="question_input",
    height=100,
    placeholder="e.g.  What is the melting temperature range reported in the paper?",
)

if st.button("🤖 Ask", type="primary", use_container_width=True):
    if not question or not question.strip():
        st.warning("Type a question first.")
    elif mode == "raw" and not selected_doc_ids:
        st.warning("Select at least one Ready document for Raw Mode.")
    else:
        with st.spinner(
            "Generating answer… Raw Mode may take longer (NFR-6)." if mode == "raw"
            else "Retrieving chunks and generating answer…"
        ):
            result = uh.handle_api_call(
                api.submit_query,
                text=question.strip(),
                mode=mode,
                k_value=k_value if mode == "rag" else None,
                document_ids=selected_doc_ids if mode == "raw" else None,
            )
        if result is not None:
            # Prepend to history (newest first)
            _SZ["query_history"].insert(0, {"question": question.strip(), "answer": result})
# ──────────────────────────────────────────────────────────────────────
# Answer display (including mode badge NFR-18, sources NFR-17, token usage)
# ──────────────────────────────────────────────────────────────────────

for entry in _SZ["query_history"]:
    q = entry["question"]
    a = entry["answer"]
    ans_mode = a.get("mode", mode)
    gen_text = a.get("generated_text", "")
    sources = a.get("sources", [])
    source_chunk_ids = a.get("source_chunk_ids")
    source_doc_ids = a.get("source_document_ids")
    llm_version = a.get("llm_model_version", "")
    token_usage = a.get("token_usage", {}) or {}

    with st.chat_message("user"):
        st.markdown(q)

    with st.chat_message("assistant"):
        # Mode badge (NFR-18)
        mode_badge = "📖 RAG" if ans_mode == "rag" else "📁 Raw Mode"
        st.caption(f"**{mode_badge}** — answered by `{llm_version}`")

        # Answer text
        st.markdown(gen_text)

        # Sources (NFR-17)
        if sources:
            with st.expander(f"Sources ({len(sources)})", expanded=False):
                for src in sources:
                    st.write(f"- **{src.get('document_filename', '?')}**, p. {src.get('page_number', '?')}")
        elif mode == "rag" and source_chunk_ids:
            st.caption("🔍 (no source references available — the answer was generated from retrieved chunks)")

        # Token usage for this call
        pt = token_usage.get("prompt_tokens", 0)
        ct = token_usage.get("completion_tokens", 0)
        tt = token_usage.get("total_tokens", 0)
        st.caption(f"Tokens: {tt} total ({pt} prompt + {ct} completion)")

        # Feedback widget (FR-31/32, NFR-28: optional, never blocks)
        st.markdown("**Was this answer helpful?**")
        fb_rating = st.radio(
            "Rating",
            options=["positive", "negative"],
            format_func=lambda r: "👍 Yes" if r == "positive" else "👎 No",
            horizontal=True,
            index=None,
            key=f"fb_rating_{a['id']}",
        )
        fb_comment = st.text_area(
            "Comment (optional)",
            key=f"fb_comment_{a['id']}",
            height=50,
            max_chars=2000,
            label_visibility="collapsed",
        )
        if st.button("Submit feedback", key=f"fb_submit_{a['id']}", use_container_width=True):
            resp = uh.handle_api_call(
                api.submit_feedback,
                answer_id=a["id"],
                rating=fb_rating,
                comment=fb_comment or None,
            )
            if resp is not None:
                st.toast("Feedback saved — thank you!", icon="💬")
        st.caption("Your feedback is optional and never blocks you (NFR-28).")

    st.divider()

# ──────────────────────────────────────────────────────────────────────
# History navigation
# ──────────────────────────────────────────────────────────────────────

if _SZ["query_history"]:
    if st.button("🗑️ Clear history", key="clear_history"):
        _SZ["query_history"] = []
        st.rerun()

st.caption(
    f"Backend: `{api.API_BASE}` | "
    "A full page refresh signs you out (the token is in-memory)."
)