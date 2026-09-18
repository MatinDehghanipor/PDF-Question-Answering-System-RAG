"""Phase 12 page: token usage & statistics (FR-33/34/35, NFR-30).

Displays per-query and per-page token usage, grouped aggregates by day
or by document, and individual usage records.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
import api_client as api
import ui_helpers as uh

st.set_page_config(page_title="Token Usage", page_icon="📊")
st.title("📊 Token Usage")

uh.require_login()
uh.sidebar_identity()
uh.show_flash()

_SZ = st.session_state

# ──────────────────────────────────────────────────────────────────────
# Summary with optional group-by
# ──────────────────────────────────────────────────────────────────────

st.subheader("Aggregate Usage")

group_by = st.selectbox(
    "Group by",
    options=[None, "day", "document"],
    format_func=lambda v: "— no grouping (grand totals)" if v is None else f"By {v}",
)

summary = uh.handle_api_call(api.get_usage_summary, group_by=group_by)
if summary is None:
    st.info("Could not fetch usage summary — backend may be down or you have no usage yet.")
else:
    total_p = summary.get("total_prompt_tokens", 0)
    total_c = summary.get("total_completion_tokens", 0)
    total_t = summary.get("total_tokens", 0)

    row = st.columns(4)
    row[0].metric("Prompt tokens", f"{total_p:,}")
    row[1].metric("Completion tokens", f"{total_c:,}")
    row[2].metric("Total tokens", f"{total_t:,}")
    row[3].metric("Avg per call", f"{total_t // max(1, total_p + total_c):,}" if total_t > 0 else "0")

    # Grouped breakdown chart
    by_group = summary.get("by_group", [])
    if by_group:
        try:
            import pandas as pd
            import altair as alt

            df = pd.DataFrame(by_group)
            df = df.rename(columns={
                "group_key": "Group",
                "total_prompt_tokens": "Prompt",
                "total_completion_tokens": "Completion",
                "total_tokens": "Total",
            })
            chart = alt.Chart(df).transform_fold(
                ["Prompt", "Completion", "Total"],
                as_=["Token Type", "Count"],
            ).mark_bar().encode(
                x=alt.X("Group:N", title=""),
                y=alt.Y("Count:Q", title="Tokens"),
                color=alt.Color("Token Type:N", scale=alt.Scale(
                    domain=["Prompt", "Completion", "Total"],
                    range=["#1f77b4", "#ff7f0e", "#2ca02c"],
                )),
                tooltip=["Group:N", alt.Tooltip("Count:Q", format=","), "Token Type:N"],
            )
            st.altair_chart(chart, use_container_width=True)
        except Exception as exc:
            st.caption(f"Chart could not be rendered: {exc}")
    else:
        st.caption("No group breakdown available (no usage data yet).")

    st.divider()
# ──────────────────────────────────────────────────────────────────────
# Individual usage records (FR-35 / NFR-30)
# ──────────────────────────────────────────────────────────────────────

st.subheader("Individual Records")

records = uh.handle_api_call(api.list_usage, skip=0, limit=200)
if records is None:
    st.info("Could not fetch usage records from the backend.")
elif not records:
    st.caption("No usage records yet — your LLM-consuming operations will appear here.")
else:
    try:
        import pandas as pd

        df = pd.DataFrame(records)

        st.dataframe(
            df[[c for c in ["id", "timestamp", "context_type", "total_tokens", "model_used", "is_estimated"]
                 if c in df.columns]],
            column_config={
                "timestamp": st.column_config.DatetimeColumn("When", format="YYYY-MM-DD HH:mm"),
                "total_tokens": st.column_config.NumberColumn("Tokens", format="%d"),
                "context_type": "Type",
                "model_used": "Model",
                "is_estimated": st.column_config.CheckboxColumn("Estimated?"),
            },
            use_container_width=True,
            hide_index=True,
        )
    except Exception as exc:
        st.caption(f"Could not render the records table: {exc}")

    # Drilldown by context id (NFR-30: per-query / per-page visibility)
    st.caption("**Drill-down** by context id (query id or page id):")
    col_id, col_type = st.columns([1, 1])
    with col_id:
        drill_id = st.number_input("Enter query or page ID", min_value=1, step=1, key="drill_id")
    with col_type:
        drill_type = st.selectbox("Type", options=["query", "page"],
                             format_func=lambda t: {                                       "query": "Query (GET /usage/queries/{id})",
                                      "page": "Page / LLM Review (GET /usage/pages/{id})",
                                  }[t])
    if st.button("Show detail", use_container_width=True, key="drill_btn"):
        if drill_type == "query":
            detail = uh.handle_api_call(api.get_query_usage, drill_id)
            if detail:
                st.json(detail)
            else:
                st.info(f"No usage records for query id={drill_id}.")
        elif drill_type == "page":
            detail = uh.handle_api_call(api.get_page_usage, drill_id)
            if detail:
                st.json(detail)
            else:
                st.info(f"No usage records for page id={drill_id}.")
    else:
        st.caption(
            "Tip: enter a query id from the table above to see token breakdown for that call."
        )

st.caption(
    f"Backend: `{api.API_BASE}` | "
    "A full page refresh signs you out (the token is in-memory)."
)