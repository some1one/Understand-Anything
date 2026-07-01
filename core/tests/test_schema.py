"""Port of packages/core/src/__tests__/schema.test.ts."""

from __future__ import annotations

import copy

import pytest

from understand_core.schema import (
    EDGE_TYPE_ALIASES,
    NODE_TYPE_ALIASES,
    auto_fix_graph,
    sanitize_graph,
    validate_graph,
)

VALID_GRAPH = {
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
        {
            "source": "node-1",
            "target": "node-1",
            "type": "imports",
            "direction": "forward",
            "weight": 0.8,
        }
    ],
    "layers": [
        {"id": "layer-1", "name": "Core", "description": "Core layer", "nodeIds": ["node-1"]}
    ],
}


def clone():
    return copy.deepcopy(VALID_GRAPH)


def _has_issue(issues, **kwargs):
    return any(all(i.get(k) == v for k, v in kwargs.items()) for i in issues)


# --- schema validation ---


def test_validates_correct_graph():
    result = validate_graph(VALID_GRAPH)
    assert result["success"] is True
    assert result["data"] is not None
    assert result["data"]["version"] == "1.0.0"
    assert result["issues"] == []


def test_rejects_missing_required_fields():
    result = validate_graph({"version": "1.0.0"})
    assert result["success"] is False
    assert result.get("fatal")


def test_invalid_node_type_drops_node_fatal_if_none():
    graph = clone()
    graph["nodes"][0]["type"] = "invalid_type"
    result = validate_graph(graph)
    assert result["success"] is False
    assert "No valid nodes" in result["fatal"]
    assert _has_issue(result["issues"], level="dropped", category="invalid-node")


def test_drops_invalid_edge_type_but_loads():
    graph = clone()
    graph["edges"][0]["type"] = "not_a_real_edge_type"
    result = validate_graph(graph)
    assert result["success"] is True
    assert len(result["data"]["edges"]) == 0
    assert _has_issue(result["issues"], level="dropped", category="invalid-edge")


def test_clamps_weight_above_one():
    graph = clone()
    graph["edges"][0]["weight"] = 1.5
    result = validate_graph(graph)
    assert result["success"] is True
    assert _has_issue(result["issues"], level="auto-corrected", category="out-of-range")


def test_clamps_weight_below_zero():
    graph = clone()
    graph["edges"][0]["weight"] = -0.1
    result = validate_graph(graph)
    assert result["success"] is True
    assert _has_issue(result["issues"], level="auto-corrected", category="out-of-range")


@pytest.mark.parametrize(
    "alias,expected",
    [("func", "function"), ("fn", "function"), ("method", "function"),
     ("interface", "class"), ("struct", "class")],
)
def test_normalizes_node_type_aliases(alias, expected):
    graph = clone()
    graph["nodes"][0]["type"] = alias
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["nodes"][0]["type"] == expected


def test_normalizes_multiple_aliased_node_types():
    graph = clone()
    graph["nodes"][0]["type"] = "func"
    graph["nodes"].append({
        "id": "node-2", "type": "pkg", "name": "utils.ts",
        "filePath": "src/utils.ts", "lineRange": [1, 30],
        "summary": "Utility helpers", "tags": ["utils"], "complexity": "simple",
    })
    graph["nodes"].append({
        "id": "node-3", "type": "struct", "name": "MyClass.ts",
        "filePath": "src/MyClass.ts", "lineRange": [1, 80],
        "summary": "A class", "tags": ["class"], "complexity": "moderate",
    })
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["nodes"][0]["type"] == "function"
    assert result["data"]["nodes"][1]["type"] == "module"
    assert result["data"]["nodes"][2]["type"] == "class"


@pytest.mark.parametrize(
    "alias,expected",
    [("extends", "inherits"), ("invokes", "calls"),
     ("relates_to", "related"), ("uses", "depends_on")],
)
def test_normalizes_edge_type_aliases(alias, expected):
    graph = clone()
    graph["edges"][0]["type"] = alias
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["edges"][0]["type"] == expected


def test_drops_tests_edge_type():
    graph = clone()
    graph["edges"][0]["type"] = "tests"
    result = validate_graph(graph)
    assert result["success"] is True
    assert len(result["data"]["edges"]) == 0
    assert _has_issue(result["issues"], level="dropped")


def test_drops_bogus_edge_types():
    graph = clone()
    graph["edges"][0]["type"] = "totally_bogus"
    result = validate_graph(graph)
    assert result["success"] is True
    assert len(result["data"]["edges"]) == 0


def test_node_aliases_no_chains():
    for target in NODE_TYPE_ALIASES.values():
        assert target not in NODE_TYPE_ALIASES


def test_edge_aliases_no_chains():
    for target in EDGE_TYPE_ALIASES.values():
        assert target not in EDGE_TYPE_ALIASES


# --- sanitizeGraph ---


def test_sanitize_null_node_fields():
    graph = clone()
    graph["nodes"][0]["filePath"] = None
    graph["nodes"][0]["lineRange"] = None
    graph["nodes"][0]["languageNotes"] = None
    result = sanitize_graph(graph)
    node = result["nodes"][0]
    assert "filePath" not in node
    assert "lineRange" not in node
    assert "languageNotes" not in node


def test_sanitize_null_edge_fields():
    graph = clone()
    graph["edges"][0]["description"] = None
    result = sanitize_graph(graph)
    assert "description" not in result["edges"][0]


def test_sanitize_lowercases_nodes():
    graph = clone()
    graph["nodes"][0]["type"] = "FILE"
    graph["nodes"][0]["complexity"] = "Simple"
    result = sanitize_graph(graph)
    assert result["nodes"][0]["type"] == "file"
    assert result["nodes"][0]["complexity"] == "simple"


def test_sanitize_lowercases_edges():
    graph = clone()
    graph["edges"][0]["type"] = "IMPORTS"
    graph["edges"][0]["direction"] = "Forward"
    result = sanitize_graph(graph)
    assert result["edges"][0]["type"] == "imports"
    assert result["edges"][0]["direction"] == "forward"


def test_sanitize_null_layers_to_empty():
    graph = clone()
    graph["layers"] = None
    result = sanitize_graph(graph)
    assert result["layers"] == []


def test_sanitize_passes_through_non_object_items():
    graph = {"nodes": [None, "garbage", 42], "edges": [None], "layers": []}
    result = sanitize_graph(graph)
    assert result["nodes"] == [None, "garbage", 42]
    assert result["edges"] == [None]


# --- autoFixGraph ---


def test_autofix_default_complexity():
    graph = clone()
    del graph["nodes"][0]["complexity"]
    data, issues = auto_fix_graph(graph)
    assert data["nodes"][0]["complexity"] == "moderate"
    assert _has_issue(issues, level="auto-corrected", category="missing-field", path="nodes[0].complexity")


def test_autofix_complexity_alias():
    graph = clone()
    graph["nodes"][0]["complexity"] = "low"
    data, issues = auto_fix_graph(graph)
    assert data["nodes"][0]["complexity"] == "simple"
    assert len(issues) == 1
    assert issues[0]["level"] == "auto-corrected"


@pytest.mark.parametrize(
    "alias,expected",
    [("low", "simple"), ("easy", "simple"), ("medium", "moderate"),
     ("intermediate", "moderate"), ("high", "complex"), ("hard", "complex"),
     ("difficult", "complex")],
)
def test_autofix_all_complexity_aliases(alias, expected):
    graph = clone()
    graph["nodes"][0]["complexity"] = alias
    data, _ = auto_fix_graph(graph)
    assert data["nodes"][0]["complexity"] == expected


def test_autofix_default_tags():
    graph = clone()
    del graph["nodes"][0]["tags"]
    data, issues = auto_fix_graph(graph)
    assert data["nodes"][0]["tags"] == []
    assert _has_issue(issues, level="auto-corrected", category="missing-field", path="nodes[0].tags")


def test_autofix_default_summary():
    graph = clone()
    del graph["nodes"][0]["summary"]
    data, issues = auto_fix_graph(graph)
    assert data["nodes"][0]["summary"] == "index.ts"
    assert _has_issue(issues, level="auto-corrected", category="missing-field", path="nodes[0].summary")


def test_autofix_default_node_type():
    graph = clone()
    del graph["nodes"][0]["type"]
    data, issues = auto_fix_graph(graph)
    assert data["nodes"][0]["type"] == "file"
    assert _has_issue(issues, level="auto-corrected", category="missing-field", path="nodes[0].type")


def test_autofix_default_direction():
    graph = clone()
    del graph["edges"][0]["direction"]
    data, issues = auto_fix_graph(graph)
    assert data["edges"][0]["direction"] == "forward"
    assert _has_issue(issues, level="auto-corrected", category="missing-field", path="edges[0].direction")


@pytest.mark.parametrize(
    "alias,expected",
    [("to", "forward"), ("outbound", "forward"), ("from", "backward"),
     ("inbound", "backward"), ("both", "bidirectional"), ("mutual", "bidirectional")],
)
def test_autofix_direction_aliases(alias, expected):
    graph = clone()
    graph["edges"][0]["direction"] = alias
    data, _ = auto_fix_graph(graph)
    assert data["edges"][0]["direction"] == expected


def test_autofix_default_weight():
    graph = clone()
    del graph["edges"][0]["weight"]
    data, issues = auto_fix_graph(graph)
    assert data["edges"][0]["weight"] == 0.5
    assert _has_issue(issues, level="auto-corrected", category="missing-field", path="edges[0].weight")


def test_autofix_coerces_string_weight():
    graph = clone()
    graph["edges"][0]["weight"] = "0.8"
    data, issues = auto_fix_graph(graph)
    assert data["edges"][0]["weight"] == 0.8
    assert _has_issue(issues, level="auto-corrected", category="type-coercion", path="edges[0].weight")


def test_autofix_clamps_out_of_range_weight():
    graph = clone()
    graph["edges"][0]["weight"] = 1.5
    data, issues = auto_fix_graph(graph)
    assert data["edges"][0]["weight"] == 1
    assert _has_issue(issues, level="auto-corrected", category="out-of-range", path="edges[0].weight")


def test_autofix_default_edge_type():
    graph = clone()
    del graph["edges"][0]["type"]
    data, issues = auto_fix_graph(graph)
    assert data["edges"][0]["type"] == "depends_on"
    assert _has_issue(issues, level="auto-corrected", category="missing-field", path="edges[0].type")


def test_autofix_no_issues_for_valid_graph():
    _, issues = auto_fix_graph(VALID_GRAPH)
    assert issues == []


def test_autofix_passes_through_non_object_items():
    graph = {"nodes": [None, "garbage"], "edges": [None], "layers": []}
    data, issues = auto_fix_graph(graph)
    assert data["nodes"] == [None, "garbage"]
    assert data["edges"] == [None]
    assert issues == []


# --- permissive validation ---


def test_drops_nodes_missing_id():
    graph = clone()
    del graph["nodes"][0]["id"]
    graph["nodes"].append({
        "id": "node-2", "type": "file", "name": "other.ts",
        "summary": "Other file", "tags": ["util"], "complexity": "simple",
    })
    result = validate_graph(graph)
    assert result["success"] is True
    assert len(result["data"]["nodes"]) == 1
    assert result["data"]["nodes"][0]["id"] == "node-2"
    assert _has_issue(result["issues"], level="dropped", category="invalid-node")


def test_drops_edges_referencing_nonexistent():
    graph = clone()
    graph["edges"][0]["target"] = "non-existent-node"
    result = validate_graph(graph)
    assert result["success"] is True
    assert len(result["data"]["edges"]) == 0
    assert _has_issue(result["issues"], level="dropped", category="invalid-reference")


def test_fatal_when_no_valid_nodes():
    graph = clone()
    del graph["nodes"][0]["id"]
    result = validate_graph(graph)
    assert result["success"] is False
    assert "No valid nodes" in result["fatal"]


def test_fatal_when_project_missing():
    graph = clone()
    del graph["project"]
    result = validate_graph(graph)
    assert result["success"] is False
    assert "project metadata" in result["fatal"]


def test_fatal_when_not_an_object():
    result = validate_graph("not an object")
    assert result["success"] is False
    assert "Invalid input" in result["fatal"]


def test_loads_mixed_good_and_bad_nodes():
    graph = clone()
    graph["nodes"].append({
        "id": "node-2", "type": "function", "name": "doThing",
        "summary": "Does a thing", "tags": ["util"], "complexity": "moderate",
    })
    graph["nodes"].append({"type": "file", "summary": "broken"})
    result = validate_graph(graph)
    assert result["success"] is True
    assert len(result["data"]["nodes"]) == 2
    assert any(i["level"] == "dropped" for i in result["issues"])


def test_filters_dangling_layer_node_ids():
    graph = clone()
    graph["layers"][0]["nodeIds"].append("non-existent-node")
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["layers"][0]["nodeIds"] == ["node-1"]


def test_drops_legacy_tour_key():
    graph = clone()
    graph["tour"] = [{"order": 1, "title": "Start here", "description": "Begin", "nodeIds": ["node-1"]}]
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"].get("tour") is None


def test_empty_issues_for_perfect_graph():
    result = validate_graph(VALID_GRAPH)
    assert result["success"] is True
    assert result["issues"] == []
    assert result.get("errors") is None


def test_autofix_loads_messy_graph():
    messy = {
        "version": "1.0.0",
        "project": VALID_GRAPH["project"],
        "nodes": [{
            "id": "n1", "type": "FILE", "name": "app.ts",
            "filePath": None, "summary": "App entry",
            "tags": None, "complexity": "HIGH",
        }],
        "edges": [{
            "source": "n1", "target": "n1", "type": "CALLS",
            "direction": "TO", "weight": "0.9",
        }],
        "layers": [{"id": "l1", "name": "Core", "description": "Core", "nodeIds": ["n1"]}],
    }
    result = validate_graph(messy)
    assert result["success"] is True
    assert result["data"]["nodes"][0]["complexity"] == "complex"
    assert result["data"]["nodes"][0]["tags"] == []
    assert result["data"]["edges"][0]["weight"] == 0.9
    assert result["data"]["edges"][0]["direction"] == "forward"
    assert len(result["issues"]) > 0
    assert all(i["level"] == "auto-corrected" for i in result["issues"])


def test_non_parseable_string_weight_defaults():
    graph = clone()
    graph["edges"][0]["weight"] = "not_a_number"
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["edges"][0]["weight"] == 0.5
    assert _has_issue(result["issues"], level="auto-corrected", category="type-coercion")


def test_fatal_when_edges_not_array():
    graph = clone()
    graph["edges"] = {"source": "node-1", "target": "node-1"}
    result = validate_graph(graph)
    assert result["success"] is False
    assert '"edges" must be an array' in result["fatal"]
    assert '"edges" must be an array when present' in result["errors"]
    assert _has_issue(result["issues"], level="fatal", category="invalid-collection", path="edges")


def test_preserves_deprecated_errors_for_dropped():
    graph = clone()
    graph["edges"][0]["target"] = "non-existent-node"
    result = validate_graph(graph)
    assert result["success"] is True
    assert 'edges[0]: target "non-existent-node" does not exist in nodes — removed' in result["errors"]


# --- extended node/edge types ---


@pytest.mark.parametrize(
    "node_type",
    ["config", "document", "service", "table", "endpoint", "pipeline", "schema", "resource"],
)
def test_validates_new_node_types(node_type):
    graph = clone()
    graph["nodes"][0]["type"] = node_type
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["nodes"][0]["type"] == node_type


@pytest.mark.parametrize(
    "edge_type",
    ["deploys", "serves", "migrates", "documents", "provisions", "routes", "defines_schema", "triggers"],
)
def test_validates_new_edge_types(edge_type):
    graph = clone()
    graph["edges"][0]["type"] = edge_type
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["edges"][0]["type"] == edge_type


@pytest.mark.parametrize(
    "alias,canonical",
    [("container", "service"), ("doc", "document"), ("business_flow", "flow"),
     ("route", "endpoint"), ("setting", "config"), ("infra", "resource"),
     ("migration", "table")],
)
def test_autofix_new_node_type_aliases(alias, canonical):
    graph = clone()
    graph["nodes"][0]["type"] = alias
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["nodes"][0]["type"] == canonical


@pytest.mark.parametrize(
    "alias,canonical",
    [("describes", "documents"), ("creates", "provisions"), ("exposes", "serves")],
)
def test_autofix_new_edge_type_aliases(alias, canonical):
    graph = clone()
    graph["edges"][0]["type"] = alias
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["edges"][0]["type"] == canonical


def test_accepts_bare_string_id():
    graph = clone()
    graph["nodes"][0]["id"] = "src/foo.ts"
    result = validate_graph(graph)
    assert result["success"] is True
