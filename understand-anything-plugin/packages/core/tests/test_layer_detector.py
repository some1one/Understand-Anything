"""Port of ``__tests__/layer-detector.test.ts``."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from understand_core.analyzer.layer_detector import (
    apply_llm_layers,
    build_layer_detection_prompt,
    detect_layers,
    parse_layer_detection_response,
)
from understand_core.analyzer.llm_analyzer import LLMLayer
from understand_core.types import GraphNode, GraphProject, KnowledgeGraph


def make_node(**overrides) -> GraphNode:
    base = {
        "type": "file",
        "summary": "",
        "tags": [],
        "complexity": "simple",
    }
    base.update(overrides)
    return GraphNode.model_construct(**base)


def make_graph(nodes) -> KnowledgeGraph:
    project = GraphProject.model_construct(
        name="test-project",
        languages=["typescript"],
        frameworks=[],
        description="A test project",
        analyzedAt=datetime.now(timezone.utc).isoformat(),
        gitCommitHash="abc123",
    )
    return KnowledgeGraph.model_construct(
        version="1.0.0", project=project, nodes=nodes, edges=[], layers=[]
    )


class TestDetectLayers:
    def test_api_routes_layer(self):
        graph = make_graph(
            [
                make_node(id="f1", name="users.ts", filePath="src/routes/users.ts"),
                make_node(id="f2", name="auth.ts", filePath="src/controllers/auth.ts"),
                make_node(id="f3", name="health.ts", filePath="src/api/health.ts"),
            ]
        )
        layers = detect_layers(graph)
        api = next((l for l in layers if l.name == "API Layer"), None)
        assert api is not None
        assert "f1" in api.nodeIds
        assert "f2" in api.nodeIds
        assert "f3" in api.nodeIds

    def test_data_layer(self):
        graph = make_graph(
            [
                make_node(id="f1", name="User.ts", filePath="src/models/User.ts"),
                make_node(id="f2", name="Post.ts", filePath="src/entity/Post.ts"),
                make_node(id="f3", name="UserRepo.ts", filePath="src/repository/UserRepo.ts"),
            ]
        )
        layers = detect_layers(graph)
        data = next((l for l in layers if l.name == "Data Layer"), None)
        assert data is not None
        assert "f1" in data.nodeIds
        assert "f2" in data.nodeIds
        assert "f3" in data.nodeIds

    def test_unmatched_to_core(self):
        graph = make_graph(
            [
                make_node(id="f1", name="main.ts", filePath="src/main.ts"),
                make_node(id="f2", name="app.ts", filePath="src/app.ts"),
            ]
        )
        layers = detect_layers(graph)
        core = next((l for l in layers if l.name == "Core"), None)
        assert core is not None
        assert "f1" in core.nodeIds
        assert "f2" in core.nodeIds

    def test_unique_kebab_ids(self):
        graph = make_graph(
            [
                make_node(id="f1", name="users.ts", filePath="src/routes/users.ts"),
                make_node(id="f2", name="User.ts", filePath="src/models/User.ts"),
                make_node(id="f3", name="main.ts", filePath="src/main.ts"),
            ]
        )
        layers = detect_layers(graph)
        ids = [l.id for l in layers]
        for layer_id in ids:
            assert re.match(r"^layer:", layer_id)
        assert len(set(ids)) == len(ids)

    def test_only_file_type_nodes(self):
        graph = make_graph(
            [
                make_node(id="f1", name="users.ts", type="file", filePath="src/routes/users.ts"),
                make_node(id="fn1", name="getUser", type="function", filePath="src/routes/users.ts"),
                make_node(id="c1", name="UserController", type="class", filePath="src/routes/users.ts"),
            ]
        )
        layers = detect_layers(graph)
        all_node_ids = [nid for l in layers for nid in l.nodeIds]
        assert "f1" in all_node_ids
        assert "fn1" not in all_node_ids
        assert "c1" not in all_node_ids


class TestBuildLayerDetectionPrompt:
    def test_contains_paths_and_json(self):
        graph = make_graph(
            [
                make_node(id="f1", name="index.ts", filePath="src/index.ts"),
                make_node(id="f2", name="app.ts", filePath="src/app.ts"),
            ]
        )
        prompt = build_layer_detection_prompt(graph)
        assert "src/index.ts" in prompt
        assert "src/app.ts" in prompt
        assert "JSON" in prompt


class TestParseLayerDetectionResponse:
    def test_valid_json(self):
        response = json.dumps(
            [
                {
                    "name": "API",
                    "description": "Handles HTTP requests",
                    "filePatterns": ["src/routes/", "src/controllers/"],
                },
                {
                    "name": "Data",
                    "description": "Database models and queries",
                    "filePatterns": ["src/models/"],
                },
            ]
        )
        result = parse_layer_detection_response(response)
        assert result is not None
        assert len(result) == 2
        assert result[0].name == "API"
        assert result[0].filePatterns == ["src/routes/", "src/controllers/"]

    def test_markdown_fences(self):
        response = """Here are the layers:
```json
[
  { "name": "UI", "description": "Frontend components", "filePatterns": ["src/components/"] }
]
```"""
        result = parse_layer_detection_response(response)
        assert result is not None
        assert len(result) == 1
        assert result[0].name == "UI"

    def test_invalid_input_returns_none(self):
        assert parse_layer_detection_response("not json at all") is None
        assert parse_layer_detection_response("{}") is None
        assert parse_layer_detection_response("") is None


class TestApplyLLMLayers:
    def test_assigns_and_other(self):
        graph = make_graph(
            [
                make_node(id="f1", name="users.ts", filePath="src/routes/users.ts"),
                make_node(id="f2", name="User.ts", filePath="src/models/User.ts"),
                make_node(id="f3", name="main.ts", filePath="src/main.ts"),
            ]
        )
        llm_layers = [
            LLMLayer(name="API", description="HTTP endpoints", filePatterns=["src/routes/"]),
            LLMLayer(name="Data", description="Models", filePatterns=["src/models/"]),
        ]
        layers = apply_llm_layers(graph, llm_layers)

        api = next((l for l in layers if l.name == "API"), None)
        assert api is not None
        assert "f1" in api.nodeIds

        data = next((l for l in layers if l.name == "Data"), None)
        assert data is not None
        assert "f2" in data.nodeIds

        other = next((l for l in layers if l.name == "Other"), None)
        assert other is not None
        assert "f3" in other.nodeIds
