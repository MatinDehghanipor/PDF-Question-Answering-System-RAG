"""Service layer for the PDF QA system backend.

Each module in this package corresponds to a logical component from the
SDD §4 Layer Summary:

    - auth_service      -> Auth Service
    - native_extractor  -> Native Extractor
    - quality_scorer    -> Quality Scorer
    - ocr_extractor     -> OCR Extractor
    - page_rasterizer   -> Page Rasterizer
    - chunker           -> Chunker
    - embedding_service -> Embedding Service + Vector Index / Store
    - llm_service       -> LLM Service
    - token_tracker     -> Token Usage Tracker

Phase 0 ships empty placeholders; each phase fills in the corresponding
module's implementation.
"""