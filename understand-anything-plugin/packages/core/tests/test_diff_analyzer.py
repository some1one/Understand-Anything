"""Port of diff-analyzer.test.ts."""

from __future__ import annotations

from understand_core import KnowledgeGraph

from skill_builders.diff_analyzer import build_diff_context, format_diff_analysis

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
            {"id": "file:src/index.ts", "type": "file", "name": "index.ts", "filePath": "src/index.ts", "summary": "Entry point", "tags": ["entry"], "complexity": "simple"},
            {"id": "file:src/routes.ts", "type": "file", "name": "routes.ts", "filePath": "src/routes.ts", "summary": "Routes", "tags": ["routes"], "complexity": "moderate"},
            {"id": "file:src/service.ts", "type": "file", "name": "service.ts", "filePath": "src/service.ts", "summary": "Service", "tags": ["service"], "complexity": "complex"},
            {"id": "function:src/service.ts:process", "type": "function", "name": "process", "filePath": "src/service.ts", "lineRange": [10, 30], "summary": "Process function", "tags": ["core"], "complexity": "complex"},
            {"id": "file:src/db.ts", "type": "file", "name": "db.ts", "filePath": "src/db.ts", "summary": "Database", "tags": ["db"], "complexity": "simple"},
        ],
        "edges": [
            {"source": "file:src/index.ts", "target": "file:src/routes.ts", "type": "imports", "direction": "forward", "weight": 0.9},
            {"source": "file:src/routes.ts", "target": "file:src/service.ts", "type": "calls", "direction": "forward", "weight": 0.8},
            {"source": "file:src/service.ts", "target": "function:src/service.ts:process", "type": "contains", "direction": "forward", "weight": 1.0},
            {"source": "file:src/service.ts", "target": "file:src/db.ts", "type": "reads_from", "direction": "forward", "weight": 0.7},
        ],
        "layers": [
            {"id": "layer:api", "name": "API Layer", "description": "HTTP routes", "nodeIds": ["file:src/index.ts", "file:src/routes.ts"]},
            {"id": "layer:service", "name": "Service Layer", "description": "Business logic", "nodeIds": ["file:src/service.ts", "function:src/service.ts:process"]},
            {"id": "layer:data", "name": "Data Layer", "description": "Database", "nodeIds": ["file:src/db.ts"]},
        ],
    }
)


class TestBuildDiffContext:
    def test_identifies_directly_changed_nodes(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        assert "file:src/service.ts" in [n.id for n in ctx.changedNodes]

    def test_identifies_child_nodes_of_changed_files(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        assert "function:src/service.ts:process" in [n.id for n in ctx.changedNodes]

    def test_identifies_affected_nodes_via_edges_1_hop(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        affected_ids = [n.id for n in ctx.affectedNodes]
        assert "file:src/routes.ts" in affected_ids
        assert "file:src/db.ts" in affected_ids

    def test_identifies_affected_layers(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        assert "Service Layer" in [l.name for l in ctx.affectedLayers]

    def test_identifies_impacted_edges(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        assert len(ctx.impactedEdges) > 0

    def test_handles_files_not_in_the_graph_gracefully(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/unknown.ts"])
        assert len(ctx.changedNodes) == 0
        assert "src/unknown.ts" in ctx.unmappedFiles

    def test_handles_empty_diff(self):
        ctx = build_diff_context(SAMPLE_GRAPH, [])
        assert len(ctx.changedNodes) == 0
        assert len(ctx.affectedNodes) == 0

    def test_de_duplicates_affected_nodes(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        changed_ids = {n.id for n in ctx.changedNodes}
        for affected in ctx.affectedNodes:
            assert affected.id not in changed_ids


class TestFormatDiffAnalysis:
    def test_produces_structured_markdown(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        analysis = format_diff_analysis(ctx)
        assert "## Changed Components" in analysis
        assert "## Affected Components" in analysis
        assert "## Affected Layers" in analysis

    def test_includes_risk_assessment_section(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/service.ts"])
        analysis = format_diff_analysis(ctx)
        assert "## Risk Assessment" in analysis

    def test_lists_unmapped_files_when_present(self):
        ctx = build_diff_context(SAMPLE_GRAPH, ["src/unknown.ts"])
        analysis = format_diff_analysis(ctx)
        assert "src/unknown.ts" in analysis
