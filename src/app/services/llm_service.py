"""LLM Service placeholder (Phase 4 stub).

Implements the "LLM Service" component (SDD §4): generates query answers
(RAG or Raw Mode) and performs LLM Review page-image extraction, while
reporting token usage for both.  Models are configurable via
``settings.LLM_ANSWER_MODEL`` and ``settings.LLM_REVIEW_MODEL`` (NFR-25,
OD-12).

Phase 4 adds the stub entry point ``trigger_llm_review(page_id, note)`` that
the review service calls when a Round-1 page is marked unsatisfied.  Real
implementation is added in Phases 5/7/8.
"""

import logging

logger = logging.getLogger(__name__)


def trigger_llm_review(page_id: int, note: str | None = None) -> None:
    """Trigger LLM Review for a page that was rejected in Round 1.

    Called by :func:`app.services.review_service.mark_unsatisfied` after a
    user marks a Round-1 page unsatisfactory.  Phase 5 replaces the body with
    real logic (render page image, call vision LLM, record token usage).

    Args:
        page_id: The id of the Page to re-extract via vision LLM.
        note: Optional free-text note from the reviewer (OD-14 default) to
            incorporate into the LLM Review prompt.
    """
    # TODO(Phase 5): implement page rasterization and vision LLM call.
    logger.info(
        "# TODO(Phase 5): render page %d as image, call vision LLM with note '%s'.",
        page_id, note,
    )