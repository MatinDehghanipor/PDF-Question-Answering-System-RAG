"""Tests for the ChromaDB vector store wrapper (Phase 6).

Covers:
    - ``get_user_collection`` creates/gets per-user collections.
    - ``upsert_chunks`` and retrieval via ``collection.get()``.
    - ``delete_chunks_for_document`` by metadata filter.
    - ``delete_chunks_by_ids`` by explicit ID list.
    - Per-user isolation (two users' collections never overlap).
"""

import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.vector_store import (
    _collection_name,
    delete_chunks_by_ids,
    delete_chunks_for_document,
    get_user_collection,
    upsert_chunks,
)


@pytest.fixture(scope="module")
def _ensure_vector_dir():
    Path(settings.VECTOR_STORE_PATH).mkdir(parents=True, exist_ok=True)
    yield


_SHARED_USER_1 = 9001
_SHARED_USER_2 = 9002


class TestCollectionNaming:
    """Verify per-user collection naming (OD-5 default)."""

    def test_collection_name_format(self):
        name = _collection_name(42)
        assert name == "user_42_chunks"

    def test_collection_name_is_deterministic(self):
        assert _collection_name(1) == _collection_name(1)
        assert _collection_name(2) != _collection_name(1)


class TestGetUserCollection:
    """``get_user_collection`` creates or retrieves per-user collections."""

    def test_get_or_creates(self, _ensure_vector_dir):
        uid = _SHARED_USER_1
        coll = get_user_collection(uid)
        assert coll.name == _collection_name(uid)

    def test_same_collection_returned_on_repeated_call(self, _ensure_vector_dir):
        uid = _SHARED_USER_1
        coll1 = get_user_collection(uid)
        coll2 = get_user_collection(uid)
        assert coll1.name == coll2.name

class TestUpsertAndRetrieve:
    """``upsert_chunks`` stores vectors that can be retrieved."""

    def _cleanup(self, user_id):
        try:
            coll = get_user_collection(user_id)
            existing = coll.get()
            if existing["ids"]:
                coll.delete(ids=existing["ids"])
        except Exception:
            pass

    def test_upsert_and_get(self, _ensure_vector_dir):
        uid = _SHARED_USER_1
        self._cleanup(uid)

        chunk_ids = ["chunk_1", "chunk_2"]
        embeddings = [[0.1] * 384, [0.2] * 384]
        documents = ["Hello world", "Test document two"]
        metadatas = [
            {"document_id": 100, "page_id": 1, "chunk_type": "text"},
            {"document_id": 100, "page_id": 1, "chunk_type": "text"},
        ]

        upsert_chunks(uid, chunk_ids, embeddings, documents, metadatas)

        coll = get_user_collection(uid)
        result = coll.get(ids=chunk_ids)
        assert len(result["ids"]) == 2
        assert "Hello world" in result["documents"]
        assert "Test document two" in result["documents"]

    def test_metadata_preserved(self, _ensure_vector_dir):
        uid = _SHARED_USER_1
        self._cleanup(uid)

        chunk_ids = ["chunk_meta_1"]
        embeddings = [[0.3] * 384]
        documents = ["Meta test"]
        metadatas = [
            {
                "document_id": 200,
                "page_id": 5,
                "chunk_type": "table",
                "reading_order": 2,
                "sub_index": 0,
                "page_number": 3,
            }
        ]

        upsert_chunks(uid, chunk_ids, embeddings, documents, metadatas)

        coll = get_user_collection(uid)
        result = coll.get(ids=chunk_ids)
        meta = result["metadatas"][0]
        assert meta["document_id"] == 200
        assert meta["page_id"] == 5
        assert meta["chunk_type"] == "table"
        assert meta["reading_order"] == 2
        assert meta["sub_index"] == 0


class TestDeleteChunksForDocument:
    """``delete_chunks_for_document`` removes vectors by metadata filter."""

    def _cleanup(self, user_id):
        try:
            coll = get_user_collection(user_id)
            existing = coll.get()
            if existing["ids"]:
                coll.delete(ids=existing["ids"])
        except Exception:
            pass

    def test_delete_removes_matching_document(self, _ensure_vector_dir):
        uid = _SHARED_USER_2
        self._cleanup(uid)

        # Insert chunks for two documents
        upsert_chunks(
            uid,
            ["d1c1", "d1c2", "d2c1"],
            [[0.0] * 384, [0.0] * 384, [0.0] * 384],
            ["a", "b", "c"],
            [
                {"document_id": 10},
                {"document_id": 10},
                {"document_id": 20},
            ],
        )

        delete_chunks_for_document(uid, 10)

        coll = get_user_collection(uid)
        remaining = coll.get()
        doc_ids = [m["document_id"] for m in remaining["metadatas"]]
        assert 10 not in doc_ids
        assert 20 in doc_ids
        assert len(remaining["ids"]) == 1

    def test_delete_nonexistent_does_not_raise(self, _ensure_vector_dir):
        uid = _SHARED_USER_2
        self._cleanup(uid)

        # Should not raise even if document has no vectors
        delete_chunks_for_document(uid, 99999)


class TestDeleteChunksByIds:
    """``delete_chunks_by_ids`` removes by explicit ID."""

    def _cleanup(self, user_id):
        try:
            coll = get_user_collection(user_id)
            existing = coll.get()
            if existing["ids"]:
                coll.delete(ids=existing["ids"])
        except Exception:
            pass

    def test_delete_by_ids(self, _ensure_vector_dir):
        uid = _SHARED_USER_2
        self._cleanup(uid)

        upsert_chunks(
            uid,
            ["keep_me", "delete_me"],
            [[0.0] * 384, [0.0] * 384],
            ["keep", "delete"],
            # ChromaDB rejects empty metadata dicts, so mirror what the
            # chunker always writes in production at index time.
            [{"document_id": 10}, {"document_id": 10}],
        )

        delete_chunks_by_ids(uid, ["delete_me"])

        coll = get_user_collection(uid)
        remaining = coll.get()
        assert "keep_me" in remaining["ids"]
        assert "delete_me" not in remaining["ids"]

    def test_empty_ids_does_nothing(self, _ensure_vector_dir):
        uid = _SHARED_USER_2
        self._cleanup(uid)
        # Should not raise
        delete_chunks_by_ids(uid, [])


class TestPerUserIsolation:
    """Two users' collections never overlap (NFR-10)."""

    def _cleanup(self, user_id):
        try:
            coll = get_user_collection(user_id)
            existing = coll.get()
            if existing["ids"]:
                coll.delete(ids=existing["ids"])
        except Exception:
            pass

    def test_isolation(self, _ensure_vector_dir):
        uid_a = 9101
        uid_b = 9102
        self._cleanup(uid_a)
        self._cleanup(uid_b)

        upsert_chunks(
            uid_a,
            ["a_only"],
            [[0.5] * 384],
            ["User A data"],
            [{"document_id": 1}],
        )
        upsert_chunks(
            uid_b,
            ["b_only"],
            [[0.6] * 384],
            ["User B data"],
            [{"document_id": 2}],
        )

        coll_a = get_user_collection(uid_a)
        coll_b = get_user_collection(uid_b)

        # User A's collection should NOT contain B's document
        result_a = coll_a.get()
        assert "b_only" not in result_a["ids"]
        assert "User B data" not in result_a["documents"]

        # User B's collection should NOT contain A's document
        result_b = coll_b.get()
        assert "a_only" not in result_b["ids"]
        assert "User A data" not in result_b["documents"]
        
class TestTopKSearch:
    """``top_k_search`` queries by vector similarity."""

    def _cleanup(self, user_id):
        try:
            from app.services.vector_store import get_user_collection
            coll = get_user_collection(user_id)
            existing = coll.get()
            if existing["ids"]:
                coll.delete(ids=existing["ids"])
        except Exception:
            pass

    def test_top_k_returns_expected_shape(self, _ensure_vector_dir):
        from app.services.vector_store import top_k_search, upsert_chunks, get_user_collection

        uid = 9201
        self._cleanup(uid)

        # Insert two chunks with known embeddings
        upsert_chunks(
            uid,
            ["tk_1", "tk_2"],
            [[0.1] * 384, [0.9] * 384],  # first is closer to query [0.1]*384
            ["Apple banana", "Zebra yak"],
            [{"document_id": 1}, {"document_id": 1}],
        )

        # Query with vector close to [0.1]*384
        query_vec = [0.1] * 384
        results = top_k_search(uid, query_vec, k=5)

        assert len(results) >= 1
        for r in results:
            assert "chunk_id" in r
            assert "document" in r
            assert "metadata" in r
            assert "distance" in r

    def test_top_k_returns_closest_first(self, _ensure_vector_dir):
        from app.services.vector_store import top_k_search, upsert_chunks, get_user_collection

        uid = 9202
        self._cleanup(uid)

        # The collection uses cosine distance, which only looks at the
        # DIRECTION of the vectors: two uniform positive vectors point the
        # same way and would tie at distance 0, so the two chunks must point
        # in different directions for this test to mean anything.
        upsert_chunks(
            uid,
            ["far", "close"],
            [[0.1, 0.9] * 192, [0.95, 0.05] * 192],
            ["Far chunk", "Close chunk"],
            [{"document_id": 1}, {"document_id": 1}],
        )

        query_vec = [1.0, 0.0] * 192
        results = top_k_search(uid, query_vec, k=2)

        assert len(results) == 2
        # "close" points almost the same way as the query (distance ~0.001),
        # "far" is nearly orthogonal (distance ~0.89): "close" must be first.
        assert results[0]["chunk_id"] == "close"
        assert results[0]["distance"] <= results[1]["distance"]

    def test_top_k_returns_fewer_than_k_when_not_enough_chunks(self, _ensure_vector_dir):
        from app.services.vector_store import top_k_search, upsert_chunks

        uid = 9203
        self._cleanup(uid)

        upsert_chunks(uid, ["only_one"], [[0.5] * 384], ["Solo"], [{"document_id": 1}])

        query_vec = [0.5] * 384
        results = top_k_search(uid, query_vec, k=10)
        assert len(results) == 1

    def test_top_k_respects_user_isolation(self, _ensure_vector_dir):
        from app.services.vector_store import top_k_search, upsert_chunks

        uid_a = 9204
        uid_b = 9205
        self._cleanup(uid_a)
        self._cleanup(uid_b)

        upsert_chunks(uid_a, ["a_only"], [[0.1] * 384], ["User A"], [{"document_id": 11}])
        upsert_chunks(uid_b, ["b_only"], [[0.9] * 384], ["User B"], [{"document_id": 12}])

        query_vec = [0.1] * 384
        results_a = top_k_search(uid_a, query_vec, k=5)
        results_b = top_k_search(uid_b, query_vec, k=5)

        # A sees its own, B sees its own
        assert any("User A" in r["document"] for r in results_a)
        assert all("User B" not in r["document"] for r in results_a)
        assert any("User B" in r["document"] for r in results_b)
        assert all("User A" not in r["document"] for r in results_b)
