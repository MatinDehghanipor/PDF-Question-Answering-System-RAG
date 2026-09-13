"""LLM Service placeholder.

Implements the "LLM Service" component (SDD §4): generates query answers
(RAG or Raw Mode) and performs LLM Review page-image extraction, while
reporting token usage for both.  Models are configurable via
``settings.LLM_ANSWER_MODEL`` and ``settings.LLM_REVIEW_MODEL`` (NFR-25,
OD-12).  Real implementation is added in Phases 5/7/8 — no business logic yet.
"""

# TODO(Phase 5/7/8): implement generate_answer(), review_page_image(),
# each returning token usage for the Token Usage Tracker.