"""Port of ``__tests__/normalize-graph.test.ts``."""

from __future__ import annotations

from datetime import datetime, timezone

from understand_core.analyzer.normalize_graph import (
    normalize_batch_output,
    normalize_complexity,
    normalize_node_id,
)
from understand_core.schema import validate_graph


class TestNormalizeNodeId:
    def test_correct_file_id_unchanged(self):
        assert normalize_node_id("file:src/index.ts", {"type": "file"}) == "file:src/index.ts"

    def test_correct_func_id_unchanged(self):
        assert (
            normalize_node_id("func:src/utils.ts:formatDate", {"type": "function"})
            == "func:src/utils.ts:formatDate"
        )

    def test_correct_class_id_unchanged(self):
        assert (
            normalize_node_id("class:src/models/User.ts:User", {"type": "class"})
            == "class:src/models/User.ts:User"
        )

    def test_fixes_double_prefix(self):
        assert normalize_node_id("file:file:src/foo.ts", {"type": "file"}) == "file:src/foo.ts"

    def test_strips_project_name_prefix_with_valid_prefix(self):
        assert (
            normalize_node_id("my-project:file:src/foo.ts", {"type": "file"})
            == "file:src/foo.ts"
        )

    def test_strips_project_name_prefix_bare_path(self):
        assert (
            normalize_node_id("my-project:src/foo.ts", {"type": "file"})
            == "file:src/foo.ts"
        )

    def test_adds_file_prefix_to_bare_paths(self):
        assert (
            normalize_node_id("frontend/src/utils/constants.ts", {"type": "file"})
            == "file:frontend/src/utils/constants.ts"
        )

    def test_reconstructs_func_id_from_filepath_name(self):
        assert (
            normalize_node_id(
                "formatDate",
                {"type": "function", "filePath": "src/utils.ts", "name": "formatDate"},
            )
            == "func:src/utils.ts:formatDate"
        )

    def test_reconstructs_class_id_from_filepath_name(self):
        assert (
            normalize_node_id(
                "User",
                {"type": "class", "filePath": "src/models/User.ts", "name": "User"},
            )
            == "class:src/models/User.ts:User"
        )

    def test_trims_whitespace(self):
        assert normalize_node_id("  file:src/foo.ts  ", {"type": "file"}) == "file:src/foo.ts"

    def test_module_and_concept_prefixes(self):
        assert normalize_node_id("module:auth", {"type": "module"}) == "module:auth"
        assert normalize_node_id("concept:caching", {"type": "concept"}) == "concept:caching"

    def test_project_prefix_before_non_code_prefix(self):
        assert (
            normalize_node_id("my-project:service:docker-compose.yml", {"type": "file"})
            == "service:docker-compose.yml"
        )

    def test_empty_input(self):
        assert normalize_node_id("", {"type": "file"}) == ""

    def test_unknown_node_type_untouched(self):
        assert normalize_node_id("some-id", {"type": "widget"}) == "some-id"

    def test_non_code_type_ids_unchanged(self):
        assert normalize_node_id("config:tsconfig.json", {"type": "config"}) == "config:tsconfig.json"
        assert normalize_node_id("document:README.md", {"type": "document"}) == "document:README.md"
        assert (
            normalize_node_id("service:docker-compose.yml", {"type": "service"})
            == "service:docker-compose.yml"
        )
        assert (
            normalize_node_id("table:migrations/001.sql:users", {"type": "table"})
            == "table:migrations/001.sql:users"
        )
        assert (
            normalize_node_id("endpoint:src/routes.ts:GET /api/users", {"type": "endpoint"})
            == "endpoint:src/routes.ts:GET /api/users"
        )
        assert (
            normalize_node_id("pipeline:.github/workflows/ci.yml", {"type": "pipeline"})
            == "pipeline:.github/workflows/ci.yml"
        )
        assert normalize_node_id("schema:schema.graphql", {"type": "schema"}) == "schema:schema.graphql"
        assert normalize_node_id("resource:main.tf", {"type": "resource"}) == "resource:main.tf"

    def test_adds_prefix_for_bare_non_code(self):
        assert normalize_node_id("tsconfig.json", {"type": "config"}) == "config:tsconfig.json"
        assert normalize_node_id("README.md", {"type": "document"}) == "document:README.md"

    def test_strips_project_prefix_non_code(self):
        assert (
            normalize_node_id("my-project:config:tsconfig.json", {"type": "config"})
            == "config:tsconfig.json"
        )


class TestNormalizeComplexity:
    def test_valid_unchanged(self):
        assert normalize_complexity("simple") == "simple"
        assert normalize_complexity("moderate") == "moderate"
        assert normalize_complexity("complex") == "complex"

    def test_low_to_simple(self):
        assert normalize_complexity("low") == "simple"

    def test_high_to_complex(self):
        assert normalize_complexity("high") == "complex"

    def test_medium_to_moderate(self):
        assert normalize_complexity("medium") == "moderate"

    def test_other_aliases(self):
        assert normalize_complexity("easy") == "simple"
        assert normalize_complexity("hard") == "complex"
        assert normalize_complexity("difficult") == "complex"
        assert normalize_complexity("intermediate") == "moderate"

    def test_case_insensitive(self):
        assert normalize_complexity("LOW") == "simple"
        assert normalize_complexity("High") == "complex"
        assert normalize_complexity("MODERATE") == "moderate"

    def test_numeric_1_3_simple(self):
        assert normalize_complexity(1) == "simple"
        assert normalize_complexity(3) == "simple"

    def test_numeric_4_6_moderate(self):
        assert normalize_complexity(4) == "moderate"
        assert normalize_complexity(6) == "moderate"

    def test_numeric_7_10_complex(self):
        assert normalize_complexity(7) == "complex"
        assert normalize_complexity(10) == "complex"

    def test_free_text_to_moderate(self):
        assert normalize_complexity("detailed") == "moderate"
        assert normalize_complexity("very complex with many deps") == "moderate"

    def test_none_to_moderate(self):
        assert normalize_complexity(None) == "moderate"

    def test_zero_and_negative_to_moderate(self):
        assert normalize_complexity(0) == "moderate"
        assert normalize_complexity(-5) == "moderate"


class TestNormalizeBatchOutput:
    def test_normalizes_ids_complexity_edges(self):
        result = normalize_batch_output(
            {
                "nodes": [
                    {
                        "id": "file:src/good.ts",
                        "type": "file",
                        "name": "good.ts",
                        "filePath": "src/good.ts",
                        "summary": "A good file",
                        "tags": ["util"],
                        "complexity": "simple",
                    },
                    {
                        "id": "my-project:file:src/bad.ts",
                        "type": "file",
                        "name": "bad.ts",
                        "filePath": "src/bad.ts",
                        "summary": "Project-prefixed",
                        "tags": ["api"],
                        "complexity": "simple",
                    },
                    {
                        "id": "src/bare.ts",
                        "type": "file",
                        "name": "bare.ts",
                        "filePath": "src/bare.ts",
                        "summary": "Bare path",
                        "tags": [],
                        "complexity": 4,
                    },
                ],
                "edges": [
                    {
                        "source": "file:src/good.ts",
                        "target": "my-project:file:src/bad.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    },
                    {
                        "source": "src/bare.ts",
                        "target": "file:src/good.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    },
                ],
            }
        )

        assert len(result.nodes) == 3
        assert result.nodes[0]["id"] == "file:src/good.ts"
        assert result.nodes[1]["id"] == "file:src/bad.ts"
        assert result.nodes[2]["id"] == "file:src/bare.ts"
        assert result.nodes[2]["complexity"] == "moderate"

        assert len(result.edges) == 2
        assert result.edges[0]["source"] == "file:src/good.ts"
        assert result.edges[0]["target"] == "file:src/bad.ts"
        assert result.edges[1]["source"] == "file:src/bare.ts"

        assert result.stats.idsFixed == 2
        assert result.stats.complexityFixed == 1
        assert result.stats.edgesRewritten == 2
        assert result.stats.danglingEdgesDropped == 0

    def test_drops_dangling_edges(self):
        result = normalize_batch_output(
            {
                "nodes": [
                    {
                        "id": "file:src/a.ts",
                        "type": "file",
                        "name": "a.ts",
                        "summary": "File A",
                        "tags": [],
                        "complexity": "simple",
                    }
                ],
                "edges": [
                    {
                        "source": "file:src/a.ts",
                        "target": "file:src/nonexistent.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    }
                ],
            }
        )
        assert len(result.edges) == 0
        assert result.stats.danglingEdgesDropped == 1
        assert len(result.stats.droppedEdges) == 1
        assert result.stats.droppedEdges[0].model_dump() == {
            "source": "file:src/a.ts",
            "target": "file:src/nonexistent.ts",
            "type": "imports",
            "reason": "missing-target",
        }

    def test_dedup_nodes_keep_last(self):
        result = normalize_batch_output(
            {
                "nodes": [
                    {
                        "id": "file:src/a.ts",
                        "type": "file",
                        "name": "a.ts",
                        "summary": "First version",
                        "tags": [],
                        "complexity": "simple",
                    },
                    {
                        "id": "file:src/a.ts",
                        "type": "file",
                        "name": "a.ts",
                        "summary": "Second version",
                        "tags": ["updated"],
                        "complexity": "complex",
                    },
                ],
                "edges": [],
            }
        )
        assert len(result.nodes) == 1
        assert result.nodes[0]["summary"] == "Second version"

    def test_dedup_edges_after_rewrite(self):
        result = normalize_batch_output(
            {
                "nodes": [
                    {
                        "id": "file:src/a.ts",
                        "type": "file",
                        "name": "a.ts",
                        "summary": "A",
                        "tags": [],
                        "complexity": "simple",
                    },
                    {
                        "id": "file:src/b.ts",
                        "type": "file",
                        "name": "b.ts",
                        "summary": "B",
                        "tags": [],
                        "complexity": "simple",
                    },
                ],
                "edges": [
                    {
                        "source": "file:src/a.ts",
                        "target": "file:src/b.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    },
                    {
                        "source": "proj:file:src/a.ts",
                        "target": "file:src/b.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    },
                ],
            }
        )
        assert len(result.edges) == 1

    def test_returns_accurate_stats(self):
        result = normalize_batch_output(
            {
                "nodes": [
                    {
                        "id": "file:src/ok.ts",
                        "type": "file",
                        "name": "ok.ts",
                        "summary": "OK",
                        "tags": [],
                        "complexity": "simple",
                    },
                    {
                        "id": "proj:file:src/fix.ts",
                        "type": "file",
                        "name": "fix.ts",
                        "summary": "Needs fix",
                        "tags": [],
                        "complexity": 2,
                    },
                ],
                "edges": [
                    {
                        "source": "proj:file:src/fix.ts",
                        "target": "file:src/ok.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    },
                    {
                        "source": "file:src/ok.ts",
                        "target": "file:src/gone.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    },
                ],
            }
        )
        assert result.stats.idsFixed == 1
        assert result.stats.complexityFixed == 1
        assert result.stats.edgesRewritten == 1
        assert result.stats.danglingEdgesDropped == 1
        assert len(result.edges) == 1

    def test_resolves_edge_endpoint_variants(self):
        result = normalize_batch_output(
            {
                "nodes": [
                    {
                        "id": "src/bare.ts",
                        "type": "file",
                        "name": "bare.ts",
                        "filePath": "src/bare.ts",
                        "summary": "Bare",
                        "tags": [],
                        "complexity": "simple",
                    },
                    {
                        "id": "file:src/target.ts",
                        "type": "file",
                        "name": "target.ts",
                        "filePath": "src/target.ts",
                        "summary": "Target",
                        "tags": [],
                        "complexity": "simple",
                    },
                ],
                "edges": [
                    {
                        "source": "my-project:file:src/bare.ts",
                        "target": "file:src/target.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    }
                ],
            }
        )
        assert len(result.edges) == 1
        assert result.edges[0]["source"] == "file:src/bare.ts"
        assert result.edges[0]["target"] == "file:src/target.ts"


class TestNormalizeBatchOutputIntegration:
    def test_passes_validate_graph(self):
        result = normalize_batch_output(
            {
                "nodes": [
                    {
                        "id": "my-project:file:src/index.ts",
                        "type": "file",
                        "name": "index.ts",
                        "filePath": "src/index.ts",
                        "summary": "Entry point",
                        "tags": ["entry"],
                        "complexity": 3,
                    },
                    {
                        "id": "src/utils.ts",
                        "type": "file",
                        "name": "utils.ts",
                        "filePath": "src/utils.ts",
                        "summary": "Utilities",
                        "tags": [],
                        "complexity": "simple",
                    },
                ],
                "edges": [
                    {
                        "source": "my-project:file:src/index.ts",
                        "target": "src/utils.ts",
                        "type": "imports",
                        "direction": "forward",
                        "weight": 0.7,
                    }
                ],
            }
        )

        graph = {
            "version": "1.0.0",
            "project": {
                "name": "test",
                "languages": ["typescript"],
                "frameworks": [],
                "description": "Test project",
                "analyzedAt": datetime.now(timezone.utc).isoformat(),
                "gitCommitHash": "abc123",
            },
            "nodes": result.nodes,
            "edges": result.edges,
            "layers": [],
        }

        validation = validate_graph(graph)
        assert validation["success"] is True
        assert len(validation["data"]["nodes"]) == 2
        assert len(validation["data"]["edges"]) == 1
