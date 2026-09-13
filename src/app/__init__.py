"""PDF QA System backend application package.

This package implements the backend for a multi-user PDF Question-Answering
(RAG) system as described in the SRS (SRS_PDF_QA_System.md) and SDD
(SDD_PDF_QA_System.md) documents.  Phase 0 provides the runnable skeleton:
configuration, database schema, stub API routers, and service module
placeholders.

The architecture follows the SDD §4 layer summary:
    - Auth Service
    - Backend API / Orchestrator
    - Native Extractor / Quality Scorer / OCR Extractor / Page Rasterizer
    - Chunker / Embedding Service / LLM Service / Token Usage Tracker
    - Document and Page Registry / Answer Feedback Store
    - User Accounts DB / PDF File Storage / Vector Index / Store
"""