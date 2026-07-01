"""Tests for arch_analysis.embeddings — text building, generation with a stubbed
client, JSON persistence round-trip, and the guarded pipeline wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arch_analysis.embeddings import (
    EmbeddingResult,
    build_embeddings,
    generate_and_save,
    load_embeddings,
    node_text,
    save_embeddings,
)

NODES = [
    {
        "id": "n1",
        "type": "file",
        "name": "auth.ts",
        "summary": "Authentication module",
        "tags": ["auth", "security"],
        "complexity": "moderate",
    },
    {
        "id": "n2",
        "type": "file",
        "name": "db.ts",
        "summary": "Database connection",
        "tags": ["db"],
        "complexity": "simple",
    },
    # No meaningful text — should be skipped.
    {"id": "n3", "type": "file", "name": "", "summary": "", "tags": []},
    # Missing id — should be skipped.
    {"id": "", "type": "file", "name": "x", "summary": "y", "tags": []},
]


class StubClient:
    """Deterministic, offline embedding client. Records the batches it sees."""

    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        # Deterministic vector derived from the text length.
        return [[float(len(t) % 10)] + [0.0] * (self.dim - 1) for t in texts]


class TestNodeText:
    def test_combines_name_summary_tags(self):
        text = node_text(NODES[0])
        assert "auth.ts" in text
        assert "Authentication module" in text
        assert "auth" in text and "security" in text

    def test_empty_node_yields_empty_text(self):
        assert node_text(NODES[2]).strip() == ""


class TestBuildEmbeddings:
    def test_returns_one_vector_per_embeddable_node(self):
        client = StubClient()
        result = build_embeddings(NODES, client, model="stub-model")
        assert set(result.embeddings) == {"n1", "n2"}
        assert all(len(v) == 4 for v in result.embeddings.values())

    def test_records_model_and_dim(self):
        result = build_embeddings(NODES, StubClient(dim=4), model="stub-model")
        assert result.model == "stub-model"
        assert result.dim == 4

    def test_batches_respect_batch_size(self):
        client = StubClient()
        build_embeddings(NODES, client, model="m", batch_size=1)
        # Two embeddable nodes, batch_size=1 → two calls of one text each.
        assert len(client.calls) == 2
        assert all(len(c) == 1 for c in client.calls)

    def test_skips_nodes_without_text_or_id(self):
        result = build_embeddings(NODES, StubClient(), model="m")
        assert "n3" not in result.embeddings
        assert "" not in result.embeddings


class TestPersistence:
    def test_save_load_round_trip(self, tmp_path: Path):
        result = build_embeddings(NODES, StubClient(), model="stub-model")
        path = tmp_path / "embeddings.json"
        save_embeddings(path, result)
        loaded = load_embeddings(path)
        assert loaded == result

    def test_serialized_shape_matches_contract(self, tmp_path: Path):
        result = build_embeddings(NODES, StubClient(dim=4), model="stub-model")
        path = tmp_path / "embeddings.json"
        save_embeddings(path, result)
        raw = json.loads(path.read_text())
        assert set(raw) == {"model", "dim", "embeddings"}
        assert raw["model"] == "stub-model"
        assert raw["dim"] == 4
        assert isinstance(raw["embeddings"], dict)
        assert isinstance(raw["embeddings"]["n1"], list)

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert load_embeddings(tmp_path / "nope.json") is None


class TestGenerateAndSave:
    def test_writes_alongside_graph(self, tmp_path: Path):
        ua_dir = tmp_path / ".understand-anything"
        ua_dir.mkdir()
        out = generate_and_save(tmp_path, NODES, client=StubClient(), model="stub-model")
        assert out == ua_dir / "embeddings.json"
        loaded = load_embeddings(out)
        assert loaded is not None
        assert set(loaded.embeddings) == {"n1", "n2"}
