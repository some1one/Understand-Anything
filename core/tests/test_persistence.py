"""Port of packages/core/src/persistence/persistence.test.ts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from understand_core.persistence import (
    load_config,
    load_fingerprints,
    load_graph,
    load_meta,
    save_config,
    save_fingerprints,
    save_graph,
    save_meta,
)

SAMPLE_GRAPH = {
    "version": "1.0.0",
    "project": {
        "name": "test-project",
        "languages": ["typescript"],
        "frameworks": ["vitest"],
        "description": "A test project",
        "analyzedAt": "2026-03-14T00:00:00.000Z",
        "gitCommitHash": "abc123",
    },
    "nodes": [
        {
            "id": "node-1",
            "type": "file",
            "name": "index.ts",
            "filePath": "src/index.ts",
            "lineRange": [1, 50],
            "summary": "Entry point",
            "tags": ["entry"],
            "complexity": "simple",
        }
    ],
    "edges": [
        {"source": "node-1", "target": "node-1", "type": "imports", "direction": "forward", "weight": 0.8}
    ],
    "layers": [{"id": "layer-1", "name": "Core", "description": "Core layer", "nodeIds": ["node-1"]}],
}

SAMPLE_META = {
    "lastAnalyzedAt": "2026-03-14T00:00:00.000Z",
    "gitCommitHash": "abc123",
    "version": "1.0.0",
    "analyzedFiles": 42,
}


# --- saveGraph / loadGraph ---


def test_writes_graph_file(tmp_path):
    save_graph(str(tmp_path), SAMPLE_GRAPH)
    assert (tmp_path / ".understand-anything" / "knowledge-graph.json").exists()


def test_reads_back_graph(tmp_path):
    save_graph(str(tmp_path), SAMPLE_GRAPH)
    loaded = load_graph(str(tmp_path))
    assert loaded is not None
    # validateGraph normalizes lineRange tuple -> list; compare as JSON
    assert loaded == SAMPLE_GRAPH


def test_returns_none_when_no_graph(tmp_path):
    assert load_graph(str(tmp_path)) is None


def test_throws_on_fatally_invalid_graph(tmp_path):
    invalid = {**SAMPLE_GRAPH, "project": None}
    save_graph(str(tmp_path), invalid)
    with pytest.raises(ValueError, match="Invalid knowledge graph"):
        load_graph(str(tmp_path))


def test_skips_validation_when_disabled(tmp_path):
    invalid = {**SAMPLE_GRAPH, "version": 123}
    save_graph(str(tmp_path), invalid)
    loaded = load_graph(str(tmp_path), validate=False)
    assert loaded is not None
    assert loaded["version"] == 123


# --- saveMeta / loadMeta ---


def test_writes_meta_file(tmp_path):
    save_meta(str(tmp_path), SAMPLE_META)
    assert (tmp_path / ".understand-anything" / "meta.json").exists()


def test_reads_back_meta(tmp_path):
    save_meta(str(tmp_path), SAMPLE_META)
    assert load_meta(str(tmp_path)) == SAMPLE_META


def test_returns_none_when_no_meta(tmp_path):
    assert load_meta(str(tmp_path)) is None


# --- saveFingerprints / loadFingerprints ---

SAMPLE_FINGERPRINTS = {
    "version": "1.0.0",
    "gitCommitHash": "abc123",
    "generatedAt": "2026-03-14T00:00:00.000Z",
    "files": {
        "src/index.ts": {
            "filePath": "src/index.ts",
            "contentHash": "deadbeef",
            "functions": [],
            "classes": [],
            "imports": [],
            "exports": [],
            "totalLines": 10,
            "hasStructuralAnalysis": False,
        }
    },
}


def test_round_trips_fingerprints(tmp_path):
    save_fingerprints(str(tmp_path), SAMPLE_FINGERPRINTS)
    assert load_fingerprints(str(tmp_path)) == SAMPLE_FINGERPRINTS


def test_returns_none_when_no_fingerprints(tmp_path):
    assert load_fingerprints(str(tmp_path)) is None


def test_returns_none_when_fingerprints_corrupted(tmp_path):
    save_fingerprints(str(tmp_path), SAMPLE_FINGERPRINTS)
    (tmp_path / ".understand-anything" / "fingerprints.json").write_text("{{not valid json!!")
    assert load_fingerprints(str(tmp_path)) is None


# --- saveConfig / loadConfig ---


def test_round_trips_config(tmp_path):
    save_config(str(tmp_path), {"autoUpdate": True})
    assert load_config(str(tmp_path)) == {"autoUpdate": True}


def test_default_config_when_none(tmp_path):
    assert load_config(str(tmp_path)) == {"autoUpdate": False}


def test_default_config_when_corrupted(tmp_path):
    save_config(str(tmp_path), {"autoUpdate": True})
    (tmp_path / ".understand-anything" / "config.json").write_text("not json!!")
    assert load_config(str(tmp_path)) == {"autoUpdate": False}


def test_sanitises_absolute_filepaths_outside_root(tmp_path):
    """Absolute paths outside the project root collapse to basename on save."""
    graph = json.loads(json.dumps(SAMPLE_GRAPH))
    graph["nodes"][0]["filePath"] = "/Users/alice/company/src/secret.ts"
    save_graph(str(tmp_path), graph)
    raw = json.loads((tmp_path / ".understand-anything" / "knowledge-graph.json").read_text())
    assert raw["nodes"][0]["filePath"] == "secret.ts"


def test_sanitises_absolute_filepaths_inside_root(tmp_path):
    graph = json.loads(json.dumps(SAMPLE_GRAPH))
    graph["nodes"][0]["filePath"] = str(Path(tmp_path) / "src" / "index.ts")
    save_graph(str(tmp_path), graph)
    raw = json.loads((tmp_path / ".understand-anything" / "knowledge-graph.json").read_text())
    assert raw["nodes"][0]["filePath"] == "src/index.ts"
