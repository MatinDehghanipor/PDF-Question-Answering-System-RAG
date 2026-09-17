"""Shared test fixtures and configuration.

Provides the suite-wide test environment — an isolated database, PDF storage and
vector store per test session — plus the fakes that keep the tests fast and
hermetic, and the per-test storage-directory helper.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Isolated test environment
# ──────────────────────────────────────────────────────────────────────────────
# ``app.core.config.settings`` is instantiated when ``app.core.config`` is first
# imported, so these overrides must be in place *before* any ``app.*`` import.
# pytest imports conftest.py before the test modules, which makes this module the
# right place: the suite then runs against its own SQLite file, its own PDF
# storage directory and its own Chroma directory instead of the developer's
# ``data/`` tree.  That also removes the "database is locked" failures caused by
# sharing ``data/app.db`` with a running ``uvicorn`` or a second pytest process,
# and makes ``pytest`` work from any working directory (the paths are absolute).
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="pdfqa_tests_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'app.db').as_posix()}"
os.environ["FILE_STORAGE_PATH"] = str(_TEST_ROOT / "pdfs")
os.environ["VECTOR_STORE_PATH"] = str(_TEST_ROOT / "vector_store")

from app.core.config import settings  # noqa: E402  (must follow the env setup above)


def _fake_embedding(texts: list[str]) -> list[list[float]]:
    """Deterministic stand-in for ``embedding_service.embed_texts``.

    The dimensionality does not need to match the real model: every test that
    asserts on vectors supplies its own 384-dim vectors explicitly.
    """
    return [[0.01, -0.02, 0.03]] * len(texts)


def _release_services() -> None:
    """Best-effort release of long-lived handles before deleting the temp tree."""
    from app.core.database import engine

    engine.dispose()

    from app.services import vector_store

    client = vector_store._client
    if client is not None:
        try:
            # Chroma keeps its own SQLite file open; stopping the system releases it.
            client._system.stop()
        except Exception:  # pragma: no cover - depends on Chroma internals
            pass
        vector_store._client = None


@pytest.fixture(scope="session", autouse=True)
def test_environment() -> Iterator[None]:
    """Create the isolated schema and storage directories once per test session.

    ``Base.metadata.create_all`` builds the schema straight from the models, so
    the suite no longer depends on a migrated ``data/app.db``.
    """
    import app.models  # noqa: F401  registers every model on Base.metadata
    from app.core.database import Base, engine

    Path(settings.FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    Path(settings.VECTOR_STORE_PATH).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    yield

    _release_services()
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def fake_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the sentence-transformers model out of every test.

    ``chunker`` and ``retrieval_service`` do
    ``from app.services.embedding_service import embed_texts``, so the name has to
    be replaced in each module that imported it — not only where it is defined.
    Without this, the first approval or ``retrieve_top_k`` call loads the real
    ~90 MB model (~27 s), and every test that embeds fails when the model cannot
    be downloaded.
    """
    from app.services import chunker
    from app.services import embedding_service
    from app.services import retrieval_service

    monkeypatch.setattr(embedding_service, "embed_texts", _fake_embedding)
    monkeypatch.setattr(chunker, "embed_texts", _fake_embedding)
    monkeypatch.setattr(retrieval_service, "embed_texts", _fake_embedding)


@pytest.fixture
def fake_vector_store(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace vector-store writes and retrieval with a canned result (opt-in).

    Returns:
        A mutable ``state`` dict, pre-filled with canned metadata.  Tests should
        pass it to their upload helper, which replaces the values with the real
        document/page/chunk identity so assertions can compare against real data.
    """
    from app.services import chunker
    from app.services import retrieval_service
    from app.services import vector_store

    state: dict = {
        "chunk_id": "chunk_1",
        "document_id": 1,
        "document_filename": "rag_test.pdf",
        "page_id": 1,
        "page_number": 1,
    }

    def _noop_upsert(user_id, chunk_ids, vectors, documents, metadatas) -> None:
        return None

    def _fake_top_k(user_id, query_vector, k) -> list[dict]:
        return [
            {
                "chunk_id": state["chunk_id"],
                "metadata": {
                    "document_id": state["document_id"],
                    "document_filename": state["document_filename"],
                    "page_id": state["page_id"],
                    "page_number": state["page_number"],
                    "chunk_type": "text",
                    "reading_order": 0,
                    "sub_index": 0,
                },
                "document": "RAG test content about artificial intelligence.",
                "distance": 0.3,
            }
        ]

    monkeypatch.setattr(vector_store, "upsert_chunks", _noop_upsert)
    monkeypatch.setattr(vector_store, "top_k_search", _fake_top_k)
    monkeypatch.setattr(chunker, "upsert_chunks", _noop_upsert)
    monkeypatch.setattr(retrieval_service, "top_k_search", _fake_top_k)

    return state


@pytest.fixture(autouse=True)
def _ensure_storage_dir() -> None:
    """Ensure the file-storage directory exists before each test."""
    Path(settings.FILE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)