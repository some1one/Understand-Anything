"""Port of packages/core/src/__tests__/domain-persistence.test.ts."""

from __future__ import annotations

from understand_core.persistence import load_domain_graph, save_domain_graph

DOMAIN_GRAPH = {
    "version": "1.0.0",
    "project": {
        "name": "test",
        "languages": ["typescript"],
        "frameworks": [],
        "description": "test",
        "analyzedAt": "2026-04-01T00:00:00.000Z",
        "gitCommitHash": "abc123",
    },
    "nodes": [
        {
            "id": "domain:orders",
            "type": "domain",
            "name": "Orders",
            "summary": "Order management",
            "tags": [],
            "complexity": "moderate",
        }
    ],
    "edges": [],
    "layers": [],
}


def test_saves_and_loads_domain_graph(tmp_path):
    save_domain_graph(str(tmp_path), DOMAIN_GRAPH)
    loaded = load_domain_graph(str(tmp_path))
    assert loaded is not None
    assert loaded["nodes"][0]["id"] == "domain:orders"


def test_returns_none_when_no_domain_graph(tmp_path):
    assert load_domain_graph(str(tmp_path)) is None


def test_saves_to_domain_graph_file(tmp_path):
    save_domain_graph(str(tmp_path), DOMAIN_GRAPH)
    ua = tmp_path / ".understand-anything"
    assert (ua / "domain-graph.json").exists()
    assert not (ua / "knowledge-graph.json").exists()
