"""Token Usage Tracker — real implementation (Phase 5).

Implements the "Token Usage Tracker" component (SDD §4): records
prompt/completion/total token counts for both query answering and LLM Review
calls, persisting to the ``TokenUsage`` table (FR-15, FR-33).

Token counts come from the LLM provider's API response ``usage`` field
when available (NFR-29's preferred source).  If the provider does not return
usage, falls back to a local ``tiktoken``-based estimate and marks the
record with ``is_estimated = True``.

Also provides ``estimate_tokens(text) -> int`` for cases where a quick
local token count is needed without making an API call.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.enums import TokenUsageContextType
from app.models.token_usage import TokenUsage

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# tiktoken import with graceful fallback
# ──────────────────────────────────────────────────────────────────────
try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None  # type: ignore[assignment]
    _TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken not installed — token estimation fallback unavailable.")


# Default encoding for token estimation.
_DEFAULT_ENCODING = "cl100k_base"  # Used by GPT-4, GPT-3.5, text-embedding-ada-002


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def record_token_usage(
    db: Session,
    user_id: int,
    context_type: TokenUsageContextType,
    context_id: int,
    model_used: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    is_estimated: bool = False,
) -> TokenUsage:
    """Persist a token-usage record linked to a specific operation (FR-15).

    Args:
        db: SQLAlchemy session.
        user_id: The user whose operation consumed tokens.
        context_type: ``query`` (Answer.id) or ``llm_review`` (Page.id).
        context_id: The polymorphic foreign key value.
        model_used: The LLM model identifier.
        prompt_tokens: Tokens in the prompt.
        completion_tokens: Tokens in the completion.
        is_estimated: ``True`` if token counts were locally estimated because
            the provider did not report usage.

    Returns:
        The created ``TokenUsage`` ORM object (not yet committed — caller
        commits the transaction).
    """
    total = prompt_tokens + completion_tokens
    record = TokenUsage(
        user_id=user_id,
        context_type=context_type,
        context_id=context_id,
        model_used=model_used,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        is_estimated=is_estimated,
    )
    db.add(record)
    logger.debug(
        "Token usage recorded: user=%d type=%s id=%d model=%s "
        "prompt=%d completion=%d total=%d%s",
        user_id, context_type.value, context_id, model_used,
        prompt_tokens, completion_tokens, total,
        " (estimated)" if is_estimated else "",
    )
    return record


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Estimate the number of tokens in *text* using tiktoken.

    Falls back to a rough character-count heuristic if tiktoken is not
    installed.

    Args:
        text: The text to count tokens in.
        model: Optional model name to select encoding.  If ``None``, uses
            ``cl100k_base`` (covers GPT-4, GPT-3.5, text-embedding models).

    Returns:
        Estimated token count.
    """
    if not _TIKTOKEN_AVAILABLE or tiktoken is None:
        # Rough fallback: ~4 chars per token for English text.
        return max(1, len(text) // 4)

    try:
        if model:
            encoding = tiktoken.encoding_for_model(model)
        else:
            encoding = tiktoken.get_encoding(_DEFAULT_ENCODING)
        return len(encoding.encode(text))
    except Exception as exc:
        logger.debug("tiktoken encoding failed (%s); using char/4 fallback.", exc)
        return max(1, len(text) // 4)