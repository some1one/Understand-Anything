"""Port of ``analyzer/graph-builder.test.ts``."""

from __future__ import annotations

import logging

from understand_core.analyzer.graph_builder import GraphBuilder


def _find(nodes, node_id):
    return next((n for n in nodes if n.id == node_id), None)


class TestGraphBuilder:
    def test_create_file_nodes(self):
        builder = GraphBuilder("test-project", "abc123")
        builder.add_file(
            "src/index.ts",
            {"summary": "Entry point", "tags": ["entry"], "complexity": "simple"},
        )
        builder.add_file(
            "src/utils.ts",
            {
                "summary": "Utility functions",
                "tags": ["utility"],
                "complexity": "moderate",
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 2
        n0 = graph.nodes[0]
        assert n0.id == "file:src/index.ts"
        assert n0.type == "file"
        assert n0.name == "index.ts"
        assert n0.filePath == "src/index.ts"
        assert n0.summary == "Entry point"
        assert n0.tags == ["entry"]
        assert n0.complexity == "simple"
        n1 = graph.nodes[1]
        assert n1.id == "file:src/utils.ts"
        assert n1.name == "utils.ts"
        assert n1.summary == "Utility functions"

    def test_function_and_class_nodes(self):
        builder = GraphBuilder("test-project", "abc123")
        analysis = {
            "functions": [
                {
                    "name": "processData",
                    "lineRange": [10, 25],
                    "params": ["input"],
                    "returnType": "string",
                },
                {"name": "validate", "lineRange": [30, 40], "params": ["data"]},
            ],
            "classes": [
                {
                    "name": "DataStore",
                    "lineRange": [50, 100],
                    "methods": ["get", "set"],
                    "properties": ["data"],
                }
            ],
            "imports": [],
            "exports": [],
        }
        builder.add_file_with_analysis(
            "src/service.ts",
            analysis,
            {
                "summary": "Service module",
                "tags": ["service"],
                "complexity": "complex",
                "fileSummary": "Handles data processing",
                "summaries": {
                    "processData": "Processes raw input data",
                    "validate": "Validates data format",
                    "DataStore": "Manages stored data",
                },
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 4

        file_node = _find(graph.nodes, "file:src/service.ts")
        assert file_node is not None
        assert file_node.type == "file"
        assert file_node.summary == "Handles data processing"

        func_node = _find(graph.nodes, "function:src/service.ts:processData")
        assert func_node is not None
        assert func_node.type == "function"
        assert func_node.name == "processData"
        assert func_node.lineRange == [10, 25]
        assert func_node.summary == "Processes raw input data"

        validate_node = _find(graph.nodes, "function:src/service.ts:validate")
        assert validate_node is not None
        assert validate_node.summary == "Validates data format"

        class_node = _find(graph.nodes, "class:src/service.ts:DataStore")
        assert class_node is not None
        assert class_node.type == "class"
        assert class_node.name == "DataStore"
        assert class_node.summary == "Manages stored data"

    def test_contains_edges(self):
        builder = GraphBuilder("test-project", "abc123")
        analysis = {
            "functions": [{"name": "helper", "lineRange": [5, 15], "params": []}],
            "classes": [
                {
                    "name": "Widget",
                    "lineRange": [20, 50],
                    "methods": [],
                    "properties": [],
                }
            ],
            "imports": [],
            "exports": [],
        }
        builder.add_file_with_analysis(
            "src/widget.ts",
            analysis,
            {
                "summary": "Widget module",
                "tags": [],
                "complexity": "moderate",
                "fileSummary": "Widget component",
                "summaries": {"helper": "Helper function", "Widget": "Widget class"},
            },
        )
        graph = builder.build()
        contains = [e for e in graph.edges if e.type == "contains"]
        assert len(contains) == 2
        assert contains[0].source == "file:src/widget.ts"
        assert contains[0].target == "function:src/widget.ts:helper"
        assert contains[0].direction == "forward"
        assert contains[0].weight == 1
        assert contains[1].source == "file:src/widget.ts"
        assert contains[1].target == "class:src/widget.ts:Widget"

    def test_import_edges(self):
        builder = GraphBuilder("test-project", "abc123")
        builder.add_file("src/index.ts", {"summary": "Entry", "tags": [], "complexity": "simple"})
        builder.add_file("src/utils.ts", {"summary": "Utils", "tags": [], "complexity": "simple"})
        builder.add_import_edge("src/index.ts", "src/utils.ts")
        graph = builder.build()
        imports = [e for e in graph.edges if e.type == "imports"]
        assert len(imports) == 1
        assert imports[0].source == "file:src/index.ts"
        assert imports[0].target == "file:src/utils.ts"
        assert imports[0].direction == "forward"

    def test_call_edges(self):
        builder = GraphBuilder("test-project", "abc123")
        builder.add_call_edge("src/index.ts", "main", "src/utils.ts", "helper")
        graph = builder.build()
        calls = [e for e in graph.edges if e.type == "calls"]
        assert len(calls) == 1
        assert calls[0].source == "function:src/index.ts:main"
        assert calls[0].target == "function:src/utils.ts:helper"
        assert calls[0].direction == "forward"

    def test_project_metadata(self):
        builder = GraphBuilder("my-awesome-project", "deadbeef")
        builder.add_file("src/app.ts", {"summary": "App", "tags": [], "complexity": "simple"})
        builder.add_file("src/script.py", {"summary": "Script", "tags": [], "complexity": "simple"})
        graph = builder.build()
        assert graph.version == "1.0.0"
        assert graph.project.name == "my-awesome-project"
        assert graph.project.gitCommitHash == "deadbeef"
        assert graph.project.languages == ["python", "typescript"]
        assert graph.project.analyzedAt
        assert graph.layers == []

    def test_detect_languages_from_extensions(self):
        builder = GraphBuilder("polyglot", "hash123")
        builder.add_file("main.go", {"summary": "", "tags": [], "complexity": "simple"})
        builder.add_file("lib.rs", {"summary": "", "tags": [], "complexity": "simple"})
        builder.add_file("app.js", {"summary": "", "tags": [], "complexity": "simple"})
        graph = builder.build()
        assert graph.project.languages == ["go", "javascript", "rust"]


class TestNonCodeFileSupport:
    def test_non_code_file_node(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_non_code_file(
            "README.md",
            {
                "nodeType": "document",
                "summary": "Project documentation",
                "tags": ["documentation"],
                "complexity": "simple",
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 1
        assert graph.nodes[0].type == "document"
        assert graph.nodes[0].id == "document:README.md"

    def test_definitions(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_non_code_file_with_analysis(
            "schema.sql",
            {
                "nodeType": "file",
                "summary": "Database schema",
                "tags": ["database"],
                "complexity": "moderate",
                "definitions": [
                    {
                        "name": "users",
                        "kind": "table",
                        "lineRange": [1, 20],
                        "fields": ["id", "name", "email"],
                    }
                ],
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 2
        assert graph.nodes[1].type == "table"
        assert graph.nodes[1].name == "users"
        assert any(
            e.type == "contains" and "users" in e.target for e in graph.edges
        )

    def test_service_children(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_non_code_file_with_analysis(
            "docker-compose.yml",
            {
                "nodeType": "config",
                "summary": "Docker compose config",
                "tags": ["infra"],
                "complexity": "moderate",
                "services": [
                    {"name": "web", "image": "node:22", "ports": [3000]},
                    {"name": "db", "image": "postgres:15", "ports": [5432]},
                ],
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 3
        assert graph.nodes[1].type == "service"
        assert graph.nodes[1].name == "web"
        assert graph.nodes[2].type == "service"
        assert graph.nodes[2].name == "db"

    def test_endpoint_children(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_non_code_file_with_analysis(
            "schema.graphql",
            {
                "nodeType": "schema",
                "summary": "GraphQL schema",
                "tags": ["api"],
                "complexity": "moderate",
                "endpoints": [{"method": "Query", "path": "users", "lineRange": [5, 5]}],
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 2
        assert graph.nodes[1].type == "endpoint"

    def test_resource_children(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_non_code_file_with_analysis(
            "main.tf",
            {
                "nodeType": "resource",
                "summary": "Terraform config",
                "tags": ["infra"],
                "complexity": "moderate",
                "resources": [
                    {
                        "name": "aws_s3_bucket.main",
                        "kind": "aws_s3_bucket",
                        "lineRange": [1, 10],
                    }
                ],
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 2
        assert graph.nodes[1].type == "resource"
        assert graph.nodes[1].name == "aws_s3_bucket.main"

    def test_step_children(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_non_code_file_with_analysis(
            "Makefile",
            {
                "nodeType": "pipeline",
                "summary": "Build targets",
                "tags": ["build"],
                "complexity": "simple",
                "steps": [
                    {"name": "build", "lineRange": [1, 3]},
                    {"name": "test", "lineRange": [5, 7]},
                ],
            },
        )
        graph = builder.build()
        assert len(graph.nodes) == 3
        assert graph.nodes[1].type == "pipeline"
        assert graph.nodes[1].name == "build"

    def test_non_code_language_yaml(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_file("config.yaml", {"summary": "Config", "tags": [], "complexity": "simple"})
        graph = builder.build()
        assert "yaml" in graph.project.languages

    def test_new_non_code_extensions(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_file("schema.graphql", {"summary": "Schema", "tags": [], "complexity": "simple"})
        builder.add_file("main.tf", {"summary": "Terraform", "tags": [], "complexity": "simple"})
        builder.add_file("types.proto", {"summary": "Protobuf", "tags": [], "complexity": "simple"})
        graph = builder.build()
        assert "graphql" in graph.project.languages
        assert "terraform" in graph.project.languages
        assert "protobuf" in graph.project.languages

    def test_unknown_kind_falls_back_to_concept(self, caplog):
        builder = GraphBuilder("test", "abc123")
        with caplog.at_level(logging.WARNING):
            builder.add_non_code_file_with_analysis(
                "schema.sql",
                {
                    "nodeType": "file",
                    "summary": "Schema",
                    "tags": [],
                    "complexity": "simple",
                    "definitions": [
                        {
                            "name": "doStuff",
                            "kind": "procedure",
                            "lineRange": [1, 10],
                            "fields": [],
                        }
                    ],
                },
            )
        graph = builder.build()
        child = next((n for n in graph.nodes if n.name == "doStuff"), None)
        assert child is not None
        assert child.type == "concept"
        assert 'Unknown definition kind "procedure"' in caplog.text

    def test_duplicate_node_ids_skipped(self, caplog):
        builder = GraphBuilder("test", "abc123")
        with caplog.at_level(logging.WARNING):
            builder.add_non_code_file_with_analysis(
                "schema.sql",
                {
                    "nodeType": "file",
                    "summary": "Schema",
                    "tags": [],
                    "complexity": "simple",
                    "definitions": [
                        {"name": "users", "kind": "table", "lineRange": [1, 10], "fields": ["id"]},
                        {
                            "name": "users",
                            "kind": "table",
                            "lineRange": [12, 20],
                            "fields": ["id", "name"],
                        },
                    ],
                },
            )
        graph = builder.build()
        tables = [n for n in graph.nodes if n.name == "users"]
        assert len(tables) == 1
        assert 'Duplicate node ID "table:schema.sql:users"' in caplog.text

    def test_node_type_in_file_id_for_contains_edges(self):
        builder = GraphBuilder("test", "abc123")
        builder.add_non_code_file_with_analysis(
            "docker-compose.yml",
            {
                "nodeType": "config",
                "summary": "Docker compose config",
                "tags": [],
                "complexity": "simple",
                "services": [{"name": "web", "ports": [3000]}],
            },
        )
        graph = builder.build()
        contains = next((e for e in graph.edges if e.type == "contains"), None)
        assert contains is not None
        assert contains.source == "config:docker-compose.yml"
        assert contains.target == "service:docker-compose.yml:web"
