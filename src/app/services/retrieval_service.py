"""Retrieval Service — top-k embedding search (Phase 7).

Implements the single retrieval interface mandated by SDD §2.4's conclusion
("retrieval is isolated behind a single interface in the architecture"):
``retrieve_top_k()`` embeds the query, searches the user's Chroma collection,
and returns typed ``RetrievedChunk`` objects with enriched metadata
(document_filename, page_number, chunk_type, reading order, etc.).

Because all vector-store access goes through this one function, alternative
retrieval methods (hybrid BM25+vector, cross-encoder re-ranking, graph-based)
listed in SRS §8 future work can be swapped in without touching any other
phase's code — only this module changes.

[WORKING DEFAULT — OD-2]: k defaults to 5, clamped to [1, 20].
[WORKING DEFAULT — OD-6]: Results grouped by document_id, ordered by
    highest-scoring (minimum-distance) chunk per document descending,
    then by (page_number, reading_order, sub_index) ascending.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import List

from app.services.embedding_service import embed_texts
from app.services.vector_store import top_k_search

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A single chunk retrieved from the vector store with enriched metadata.

    Attributes:
        chunk_id: The Chroma-internal string id (``chunk_{id}`` or
            ``chunk_{id}_sub{N}`` for split text chunks).
        document_id: SQL primary key of the owning Document.
        document_filename: Original filename of the source document (from
            Chroma metadata, set at index time by :func:`chunker.split_and_index_page`).
        page_id: SQL primary key of the source Page.
        page_number: 1-based page number within the document.
        chunk_type: ``text``, ``table``, or ``image``.
        text_or_caption: The chunk's textual content — chunk text for
            ``text`` type, markdown for ``table``, caption for ``image``.
        reading_order: Order of this chunk within the page.
        sub_index: Sub-index for split text chunks (0 for non-split).
        distance: Chroma cosine distance (0 = identical, lower = more similar).
    """

    chunk_id: str
    document_id: int
    document_filename: str
    page_id: int
    page_number: int
    chunk_type: str
    text_or_caption: str
    reading_order: int
    sub_index: int
    distance: float

    @property
    def similarity_score(self) -> float:
        """Convert cosine distance to a similarity score (higher = more similar).

        Chroma returns cosine distance in [0, 2]; ``1 - distance`` gives
        a value in [-1, 1] where 1 = identical, 0 = orthogonal, -1 = opposite.
        """
        return 1.0 - self.distance


def retrieve_top_k(user_id: int, query_text: str, k: int) -> List[RetrievedChunk]:
    """Embed *query_text* and retrieve the top‑k most similar chunks for *user_id*.

    This is the **single retrieval interface** called by ``POST /query``
    (RAG Mode).  It is intentionally free of SQLAlchemy dependencies so that
    it can be unit-tested with a mock vector store alone.

    Args:
        user_id: The authenticated user whose collection to search.
        query_text: The user's natural‑language question.
        k: Maximum number of chunks to retrieve.  Chroma may return fewer
            if the user has fewer than *k* indexed chunks — that is not an error.

    Returns:
        List of :class:`RetrievedChunk` objects, ordered per OD-6 (grouped by
        document, highest-similarity document first).

    Raises:
        RuntimeError: If embedding generation fails (e.g. model not loaded).

    Note:
        The query is embedded with the **same** model used to index chunks
        (``settings.EMBEDDING_MODEL_NAME``).  Using a different embedding model
        for the query than the corpus would silently break similarity search.
        This coupling is intentional and enforced by both functions reading
        ``settings.EMBEDDING_MODEL_NAME``.
    """
    # 1. Embed the query.
    query_vectors = embed_texts([query_text])
    if not query_vectors:
        raise RuntimeError("Query embedding returned empty result.")
    query_vector = query_vectors[0]

    # 2. Search.
    raw_results = top_k_search(user_id, query_vector, k)
    if not raw_results:
        logger.info("top_k_search returned no results for user %d (query=%r).", user_id, query_text[:60])
        return []

    # 3. Resolve metadata into typed chunks.
    chunks: List[RetrievedChunk] = []
    for r in raw_results:
        meta = r.get("metadata", {})
        chunks.append(RetrievedChunk(
            chunk_id=r.get("chunk_id", ""),
            document_id=meta.get("document_id", 0),
            document_filename=meta.get("document_filename", ""),
            page_id=meta.get("page_id", 0),
            page_number=meta.get("page_number", 0),
            chunk_type=meta.get("chunk_type", "text"),
            text_or_caption=r.get("document", ""),
            reading_order=meta.get("reading_order", 0),
            sub_index=meta.get("sub_index", 0),
            distance=r.get("distance", 0.0),
        ))

    # 4. Sort per OD-6: group by document, order by highest-similarity chunk
    #    descending, then within each document by reading order ascending.
    #    Chroma distance is lower=more-similar, so we sort by minimum distance
    #    ascending to put the most-relevant document first.
    doc_groups: OrderedDict[int, List[RetrievedChunk]] = OrderedDict()
    for c in chunks:
        doc_groups.setdefault(c.document_id, []).append(c)

    # Sort within each document by (page_number, reading_order, sub_index).
    for doc_id in doc_groups:
        doc_groups[doc_id].sort(key=lambda c: (c.page_number, c.reading_order, c.sub_index))

    # Sort document groups by the minimum distance (highest similarity) of any
    # chunk in that group — ascending because lower = more similar.
    sorted_doc_ids = sorted(
        doc_groups.keys(),
        key=lambda did: min(c.distance for c in doc_groups[did]),
    )

    # Flatten into the final result list.
    result: List[RetrievedChunk] = []
    for doc_id in sorted_doc_ids:
        result.extend(doc_groups[doc_id])

    logger.debug(
        "retrieve_top_k(user=%d, k=%d) returned %d chunks from %d documents.",
        user_id, k, len(result), len(sorted_doc_ids),
    )
    return result
