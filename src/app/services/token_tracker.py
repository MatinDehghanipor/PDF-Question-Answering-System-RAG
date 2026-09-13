"""Token Usage Tracker placeholder.

Implements the "Token Usage Tracker" component (SDD §4): records
prompt/completion/embedding token counts for both query answering and
LLM Review calls, persisting to the ``TokenUsage`` table.  Real
implementation is added in Phase 10 — no business logic yet.
"""

# TODO(Phase 10): implement record_usage(user_id, context_type, context_id,
# model, prompt_tokens, completion_tokens) and query_usage aggregations.