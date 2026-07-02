"""Port of explain-builder.test.ts."""

from __future__ import annotations

from understand_core import KnowledgeGraph

from skill_builders.explain_builder import (
    build_explain_context,
    format_explain_prompt,
)

SAMPLE_GRAPH = KnowledgeGraph.model_validate(
    {
        "version": "1.0.0",
        "project": {
            "name": "test-project",
            "languages": ["typescript"],
            "frameworks": ["express"],
            "description": "A test project",
            "analyzedAt": "2026-03-14T00:00:00Z",
            "gitCommitHash": "abc123",
        },
        "nodes": [
            {"id": "file:src/auth.ts", "type": "file", "name": "auth.ts", "filePath": "src/auth.ts", "summary": "Auth module", "tags": ["auth"], "complexity": "complex"},
            {"id": "function:src/auth.ts:login", "type": "function", "name": "login", "filePath": "src/auth.ts", "lineRange": [10, 30], "summary": "Login handler", "tags": ["auth", "login"], "complexity": "moderate"},
            {"id": "function:src/auth.ts:verify", "type": "function", "name": "verify", "filePath": "src/auth.ts", "lineRange": [32, 50], "summary": "Token verification", "tags": ["auth", "jwt"], "complexity": "moderate"},
            {"id": "file:src/db.ts", "type": "file", "name": "db.ts", "filePath": "src/db.ts", "summary": "Database", "tags": ["db"], "complexity": "simple"},
        ],
        "edges": [
            {"source": "file:src/auth.ts", "target": "function:src/auth.ts:login", "type": "contains", "direction": "forward", "weight": 1.0},
            {"source": "file:src/auth.ts", "target": "function:src/auth.ts:verify", "type": "contains", "direction": "forward", "weight": 1.0},
            {"source": "function:src/auth.ts:login", "target": "file:src/db.ts", "type": "reads_from", "direction": "forward", "weight": 0.8},
        ],
        "layers": [
            {"id": "layer:auth", "name": "Auth Layer", "description": "Authentication", "nodeIds": ["file:src/auth.ts", "function:src/auth.ts:login", "function:src/auth.ts:verify"]},
        ],
    }
)


class TestBuildExplainContext:
    def test_finds_the_file_node_by_path(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/auth.ts")
        assert ctx.targetNode is not None
        assert ctx.targetNode.id == "file:src/auth.ts"

    def test_includes_child_nodes(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/auth.ts")
        names = [n.name for n in ctx.childNodes]
        assert "login" in names
        assert "verify" in names

    def test_includes_connected_nodes(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/auth.ts")
        all_ids = [n.id for n in ctx.connectedNodes]
        assert "file:src/db.ts" in all_ids

    def test_includes_the_layer(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/auth.ts")
        assert ctx.layer is not None
        assert ctx.layer.name == "Auth Layer"

    def test_returns_null_target_node_for_unknown_paths(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/unknown.ts")
        assert ctx.targetNode is None

    def test_finds_function_nodes_by_partial_path_match(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/auth.ts:login")
        assert ctx.targetNode is not None
        assert ctx.targetNode.name == "login"


class TestFormatExplainPrompt:
    def test_produces_structured_markdown_for_valid_context(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/auth.ts")
        prompt = format_explain_prompt(ctx)
        assert "auth.ts" in prompt
        assert "login" in prompt
        assert "Auth Layer" in prompt

    def test_produces_helpful_message_for_unknown_path(self):
        ctx = build_explain_context(SAMPLE_GRAPH, "src/unknown.ts")
        prompt = format_explain_prompt(ctx)
        assert "not found" in prompt
