"""Port of context-builder.test.ts."""

from __future__ import annotations

from understand_core import KnowledgeGraph

from skill_builders.context_builder import (
    build_chat_context,
    format_context_for_prompt,
)


def make_node(**overrides: object) -> dict:
    base = {
        "type": "file",
        "summary": "",
        "tags": [],
        "complexity": "simple",
    }
    base.update(overrides)
    return base


SAMPLE_NODES = [
    make_node(
        id="auth-ctrl",
        name="AuthenticationController",
        type="class",
        filePath="src/controllers/auth.ts",
        summary="Handles user login, logout, and session management",
        tags=["auth", "controller", "security"],
        complexity="complex",
        languageNotes="Uses Express middleware pattern",
    ),
    make_node(
        id="db-pool",
        name="DatabasePool",
        type="class",
        filePath="src/db/pool.ts",
        summary="Manages PostgreSQL connection pooling",
        tags=["database", "connection"],
        complexity="moderate",
    ),
    make_node(
        id="user-model",
        name="UserModel",
        type="class",
        filePath="src/models/user.ts",
        summary="ORM model for the users table",
        tags=["model", "database", "user"],
        complexity="moderate",
    ),
    make_node(
        id="auth-middleware",
        name="authMiddleware",
        type="function",
        filePath="src/middleware/auth.ts",
        summary="Express middleware that validates JWT tokens for authentication",
        tags=["auth", "middleware", "security"],
        complexity="simple",
    ),
    make_node(
        id="config",
        name="config.ts",
        type="file",
        filePath="src/config.ts",
        summary="Application configuration and environment variables",
        tags=["config", "env"],
        complexity="simple",
    ),
]

SAMPLE_EDGES = [
    {
        "source": "auth-ctrl",
        "target": "user-model",
        "type": "depends_on",
        "direction": "forward",
        "description": "AuthenticationController uses UserModel for user lookup",
        "weight": 0.9,
    },
    {
        "source": "auth-ctrl",
        "target": "auth-middleware",
        "type": "calls",
        "direction": "forward",
        "description": "Controller registers auth middleware",
        "weight": 0.7,
    },
    {
        "source": "user-model",
        "target": "db-pool",
        "type": "depends_on",
        "direction": "forward",
        "description": "UserModel uses DatabasePool for queries",
        "weight": 0.8,
    },
]

SAMPLE_LAYERS = [
    {
        "id": "layer:api",
        "name": "API Layer",
        "description": "HTTP controllers and middleware",
        "nodeIds": ["auth-ctrl", "auth-middleware"],
    },
    {
        "id": "layer:data",
        "name": "Data Layer",
        "description": "Database models and connections",
        "nodeIds": ["user-model", "db-pool"],
    },
]

SAMPLE_GRAPH = KnowledgeGraph.model_validate(
    {
        "version": "1.0.0",
        "project": {
            "name": "test-project",
            "languages": ["TypeScript"],
            "frameworks": ["Express"],
            "description": "A test project for unit tests",
            "analyzedAt": "2026-03-14T00:00:00Z",
            "gitCommitHash": "abc123",
        },
        "nodes": SAMPLE_NODES,
        "edges": SAMPLE_EDGES,
        "layers": SAMPLE_LAYERS,
    }
)


class TestBuildChatContext:
    def test_finds_relevant_nodes_for_a_query(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        assert len(ctx.relevantNodes) > 0
        node_names = [n.name for n in ctx.relevantNodes]
        assert "AuthenticationController" in node_names

    def test_includes_connected_nodes_via_1_hop_expansion(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        node_ids = [n.id for n in ctx.relevantNodes]
        assert "auth-ctrl" in node_ids
        assert "user-model" in node_ids
        assert "auth-middleware" in node_ids

    def test_includes_project_metadata(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "database")
        assert ctx.projectName == "test-project"
        assert ctx.projectDescription == "A test project for unit tests"
        assert ctx.languages == ["TypeScript"]
        assert ctx.frameworks == ["Express"]

    def test_includes_relevant_layers_containing_matched_nodes(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        layer_names = [l.name for l in ctx.relevantLayers]
        assert "API Layer" in layer_names

    def test_includes_relevant_edges_between_relevant_nodes(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        assert len(ctx.relevantEdges) > 0
        has_auth_to_user = any(
            e.source == "auth-ctrl" and e.target == "user-model"
            for e in ctx.relevantEdges
        )
        assert has_auth_to_user

    def test_stores_the_original_query(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "database pool")
        assert ctx.query == "database pool"

    def test_respects_max_nodes_parameter(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "auth", 1)
        assert len(ctx.relevantNodes) >= 1
        assert len(ctx.relevantNodes) <= len(SAMPLE_NODES)

    def test_returns_empty_relevant_nodes_for_no_matches(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "xyznonexistent")
        assert len(ctx.relevantNodes) == 0
        assert len(ctx.relevantEdges) == 0
        assert len(ctx.relevantLayers) == 0


class TestFormatContextForPrompt:
    def test_contains_node_names_and_summaries(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        formatted = format_context_for_prompt(ctx)
        assert "AuthenticationController" in formatted
        assert "Handles user login, logout, and session management" in formatted

    def test_includes_project_header_information(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        formatted = format_context_for_prompt(ctx)
        assert "test-project" in formatted
        assert "TypeScript" in formatted
        assert "Express" in formatted

    def test_includes_edge_relationship_descriptions(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        formatted = format_context_for_prompt(ctx)
        assert "AuthenticationController" in formatted
        assert "UserModel" in formatted
        assert "depends_on" in formatted

    def test_includes_layer_information_when_present(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        formatted = format_context_for_prompt(ctx)
        assert "API Layer" in formatted

    def test_includes_file_paths_for_nodes_that_have_them(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        formatted = format_context_for_prompt(ctx)
        assert "src/controllers/auth.ts" in formatted

    def test_includes_complexity_and_type_information(self):
        ctx = build_chat_context(SAMPLE_GRAPH, "authentication")
        formatted = format_context_for_prompt(ctx)
        assert "complex" in formatted
        assert "class" in formatted
