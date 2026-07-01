"""Port of onboard-builder.test.ts."""

from __future__ import annotations

from understand_core import KnowledgeGraph

from skill_builders.onboard_builder import build_onboarding_guide

SAMPLE_GRAPH_DATA = {
    "version": "1.0.0",
    "project": {
        "name": "test-project",
        "languages": ["typescript", "python"],
        "frameworks": ["express", "prisma"],
        "description": "A test REST API",
        "analyzedAt": "2026-03-14T00:00:00Z",
        "gitCommitHash": "abc123",
    },
    "nodes": [
        {"id": "file:src/index.ts", "type": "file", "name": "index.ts", "filePath": "src/index.ts", "summary": "Entry point", "tags": ["entry"], "complexity": "simple"},
        {"id": "file:src/service.ts", "type": "file", "name": "service.ts", "filePath": "src/service.ts", "summary": "Core service", "tags": ["service"], "complexity": "complex"},
        {"id": "concept:auth", "type": "concept", "name": "Auth Flow", "summary": "JWT-based authentication", "tags": ["concept", "auth"], "complexity": "complex"},
    ],
    "edges": [
        {"source": "file:src/index.ts", "target": "file:src/service.ts", "type": "imports", "direction": "forward", "weight": 0.8},
    ],
    "layers": [
        {"id": "layer:api", "name": "API Layer", "description": "Routes and handlers", "nodeIds": ["file:src/index.ts"]},
        {"id": "layer:service", "name": "Service Layer", "description": "Business logic", "nodeIds": ["file:src/service.ts"]},
    ],
}


def _graph(**overrides: object) -> KnowledgeGraph:
    data = {**SAMPLE_GRAPH_DATA, **overrides}
    return KnowledgeGraph.model_validate(data)


SAMPLE_GRAPH = _graph()


class TestOnboardBuilder:
    def test_includes_project_overview_section(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "# test-project" in guide
        assert "A test REST API" in guide

    def test_lists_languages_and_frameworks(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "typescript" in guide
        assert "express" in guide

    def test_includes_architecture_layers_section(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "## Architecture" in guide
        assert "API Layer" in guide
        assert "Service Layer" in guide

    def test_includes_key_concepts_section(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "## Key Concepts" in guide
        assert "Auth Flow" in guide

    def test_includes_getting_started_from_dependency_fan_in(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "## Getting Started" in guide
        assert "src/service.ts" in guide
        assert "explore the codebase layer by layer" in guide

    def test_does_not_include_a_guided_tour_section(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "guided tour" not in guide
        assert "Guided Tour" not in guide
        assert "Language Tip" not in guide

    def test_includes_complexity_hotspots(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "## Complexity Hotspots" in guide
        assert "service.ts" in guide

    def test_includes_file_map_section(self):
        guide = build_onboarding_guide(SAMPLE_GRAPH)
        assert "## File Map" in guide

    def test_handles_graph_with_no_layers_gracefully(self):
        guide = build_onboarding_guide(_graph(layers=[]))
        assert "# test-project" in guide

    def test_handles_graph_with_no_dependency_edges_gracefully(self):
        guide = build_onboarding_guide(_graph(edges=[]))
        assert "# test-project" in guide
