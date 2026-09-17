"""Embedding Service — real implementation (Phase 6)."""

import hashlib
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)
_model = None
_ENC = "cl100k_base"

# ──────────────────────────────────────────────────────────────────────
# FR-37 reprocessing guard
# ──────────────────────────────────────────────────────────────────────
_embedded_hashes: set[str] = set()


def _check_reembed_guard(texts: list[str]) -> None:
    """Warn if any of *texts* was already embedded (FR-37 defense-in-depth).

    Uses SHA-256 of the concatenated input to detect repeated calls with
    identical content.  This is an in-memory guard; the authoritative
    gatekeeper is the page status machine.
    """
    digest = hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()
    if digest in _embedded_hashes:
        logger.warning(
            "FR-37 guard: embed_texts called again with the same %d text(s) "
            "(hash=%s...).",
            len(texts), digest[:12],
        )
    _embedded_hashes.add(digest)


def get_embedding_model():
    global _model
    if _model is None:
        # Lazy import — sentence_transformers takes ~13s to import even
        # without loading any model.  Only pay that cost when the embedding
        # model is actually needed (first chunk indexing or query).
        from sentence_transformers import SentenceTransformer

        logger.info("Loading model '%s' ...", settings.EMBEDDING_MODEL_NAME)
        try:
            _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        except Exception as exc:
            raise RuntimeError(f"Failed to load '{settings.EMBEDDING_MODEL_NAME}': {exc}") from exc
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    _check_reembed_guard(texts)
    m = get_embedding_model()
    return [e.tolist() for e in m.encode(texts, batch_size=32, show_progress_bar=False)]


def _token_count(text: str) -> int:
    try:
        # Lazy import — tiktoken is fast but still worth deferring.
        import tiktoken
        return len(tiktoken.get_encoding(_ENC).encode(text))
    except Exception:
        return len(text) // 4


def should_split_chunk(text: str) -> bool:
    return _token_count(text) > settings.CHUNK_SIZE_TOKENS


def split_text_chunk(text: str, chunk_id: int, reading_order: int) -> list[dict]:
    # Lazy import — RecursiveCharacterTextSplitter pulls in langchain deps.
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    s = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE_TOKENS, chunk_overlap=settings.CHUNK_OVERLAP_TOKENS,
        length_function=_token_count, separators=["\n\n", "\n", ".", " ", ""],
    )
    return [{"text": t, "reading_order": reading_order, "sub_index": i, "parent_chunk_id": chunk_id}
            for i, t in enumerate(s.split_text(text))]