"""Port of embedding-search.test.ts."""

from __future__ import annotations

import pytest

from understand_core.embedding_search import SemanticSearchEngine, cosine_similarity

NODES = [
    {"id": "n1", "type": "file", "name": "auth.ts", "summary": "Authentication module", "tags": ["auth"], "complexity": "moderate"},
    {"id": "n2", "type": "file", "name": "db.ts", "summary": "Database connection", "tags": ["db"], "complexity": "simple"},
    {"id": "n3", "type": "function", "name": "login", "summary": "User login handler", "tags": ["auth", "login"], "complexity": "moderate"},
]

EMBEDDINGS = {
    "n1": [1, 0, 0, 0],
    "n2": [0, 1, 0, 0],
    "n3": [0.9, 0, 0.1, 0],
}


class TestCosineSimilarity:
    def test_returns_1_for_identical_vectors(self):
        assert cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1)

    def test_returns_0_for_orthogonal_vectors(self):
        assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0)

    def test_returns_high_similarity_for_similar_vectors(self):
        sim = cosine_similarity([1, 0, 0], [0.9, 0.1, 0])
        assert sim > 0.9

    def test_handles_zero_vectors(self):
        assert cosine_similarity([0, 0, 0], [1, 0, 0]) == 0


class TestSemanticSearchEngine:
    def test_returns_results_sorted_by_similarity(self):
        engine = SemanticSearchEngine(NODES, EMBEDDINGS)
        results = engine.search([1, 0, 0, 0])
        assert results[0].node_id == "n1"

    def test_respects_limit_parameter(self):
        engine = SemanticSearchEngine(NODES, EMBEDDINGS)
        results = engine.search([1, 0, 0, 0], limit=2)
        assert len(results) == 2

    def test_respects_threshold_parameter(self):
        engine = SemanticSearchEngine(NODES, EMBEDDINGS)
        results = engine.search([1, 0, 0, 0], threshold=0.5)
        ids = [r.node_id for r in results]
        assert "n2" not in ids

    def test_filters_by_node_type(self):
        engine = SemanticSearchEngine(NODES, EMBEDDINGS)
        results = engine.search([1, 0, 0, 0], types=["function"])
        for r in results:
            node = next(n for n in NODES if n["id"] == r.node_id)
            assert node["type"] == "function"

    def test_returns_empty_for_nodes_without_embeddings(self):
        engine = SemanticSearchEngine(NODES, {})
        results = engine.search([1, 0, 0, 0])
        assert len(results) == 0

    def test_has_embeddings_true_when_present(self):
        engine = SemanticSearchEngine(NODES, EMBEDDINGS)
        assert engine.has_embeddings() is True

    def test_has_embeddings_false_when_empty(self):
        engine = SemanticSearchEngine(NODES, {})
        assert engine.has_embeddings() is False

    def test_add_embedding_updates_index(self):
        engine = SemanticSearchEngine(NODES, {})
        assert engine.has_embeddings() is False
        engine.add_embedding("n1", [1, 0, 0, 0])
        assert engine.has_embeddings() is True
