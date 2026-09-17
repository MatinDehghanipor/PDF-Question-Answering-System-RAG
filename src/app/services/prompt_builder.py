"""Prompt Builder — RAG prompt assembly (Phase 7).

Builds the grounded prompt sent to the answering LLM by combining the user's
query with retrieved chunks, implementing:

- **OD-6**: Retrieved chunks are grouped by source document (IDs ordered by
  that document's highest-similarity chunk descending), then within each
  document group sorted by ``(page_number, reading_order, sub_index)``
  ascending, so evidence from the same document is contiguous and in
  original reading order (FR-26).

- **OD-10**: The ``RAG_PROMPT_TEMPLATE`` from :mod:`app.services.llm_service`
  is used, which instructs the LLM to ground its answer exclusively in the
  provided excerpts and cite sources inline.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import List

from app.services.llm_service import RAG_PROMPT_TEMPLATE
from app.services.retrieval_service import RetrievedChunk

logger = logging.getLogger(__name__)


def build_rag_prompt(query_text: str, retrieved_chunks: List[RetrievedChunk]) -> str:
    """Build a grounded RAG prompt from the user's query and retrieved chunks.

    Groups and orders chunks per OD-6, then applies the OD-10 prompt template.

    Args:
        query_text: The user's original natural‑language question.
        retrieved_chunks: The top‑k chunks from
            :func:`retrieval_service.retrieve_top_k`.

    Returns:
        A fully formatted prompt string ready to send to the LLM via
        :func:`llm_service.call_text_llm`.

    Note:
        OD-6 ordering is *applied here* rather than assumed to arrive
        already sorted from :func:`retrieval_service.retrieve_top_k`, so the
        prompt stays correct even if a future re-ranker, a cache, or an
        alternative retrieval back-end hands over chunks in a different
        order.  The sort is idempotent for input that is already
        OD-6-ordered.

        ``MAX_TOP_K`` is conservatively set at 20 and each chunk is ~500
        tokens, so the total prompt stays within typical LLM context windows
        without dynamic truncation.  If either bound is relaxed in the future,
        truncation logic should be added here.
    """
    if not retrieved_chunks:
        logger.info("No retrieved chunks — building empty-excerpt prompt.")
        formatted_chunks = "[No relevant excerpts were found in your documents.]"
        return RAG_PROMPT_TEMPLATE.format(
            formatted_chunks=formatted_chunks,
            query_text=query_text,
        )

    # 1. Group by document_id (OD-6 step 1).
    doc_groups: OrderedDict[int, List[RetrievedChunk]] = OrderedDict()
    for c in retrieved_chunks:
        doc_groups.setdefault(c.document_id, []).append(c)

    # 2. Within each document group, sort by (page_number, reading_order,
    #    sub_index) ascending: true reading order (OD-6 step 2 / FR-26),
    #    reusing the metadata written at index time in Phase 6.
    for doc_id in doc_groups:
        doc_groups[doc_id].sort(
            key=lambda c: (c.page_number, c.reading_order, c.sub_index)
        )

    # 3. Order the document groups by their highest-similarity chunk (OD-6
    #    step 1: whichever document contributed the single most relevant
    #    chunk is presented first).  Chroma distances are lower = more
    #    similar, so ascending minimum distance; equal scores fall back to
    #    ascending document_id so a given result set always yields the same
    #    prompt.
    ordered_doc_ids = sorted(
        doc_groups.keys(),
        key=lambda did: (min(c.distance for c in doc_groups[did]), did),
    )

    # 4. Build formatted string: one section per document group, its chunks
    #    contiguous and in reading order.
    formatted_parts: List[str] = []
    for doc_id in ordered_doc_ids:
        chunks = doc_groups[doc_id]
        filename = chunks[0].document_filename
        formatted_parts.append(f"--- Document: {filename} ---")
        for c in chunks:
            formatted_parts.append(f"[Page {c.page_number}] {c.text_or_caption}")
        formatted_parts.append("")  # blank line between document groups

    formatted_chunks = "\n".join(formatted_parts)

    # 3. Apply the OD-10 template.
    return RAG_PROMPT_TEMPLATE.format(
        formatted_chunks=formatted_chunks,
        query_text=query_text,
    )
