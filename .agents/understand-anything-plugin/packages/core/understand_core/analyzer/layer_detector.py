"""Layer detection — port of ``analyzer/layer-detector.ts``.

``detect_layers`` is heuristic (directory-path-pattern based) and conceptually
overlaps :mod:`arch_analysis.recommendations`, but that module computes a very
different signal (group roles, topological ordering, threshold-based non-code
layer suggestions) with a different output contract. The TS heuristic — assign
file nodes to named layers by matching path segments against pattern lists — is
not equivalent, so it is ported fresh here. The LLM prompt builder/parser and
``apply_llm_layers`` are likewise TS-only and ported faithfully.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..types import KnowledgeGraph, Layer


class LLMLayerResponse(BaseModel):
    """What the LLM returns for each layer in layer detection."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    description: str = ""
    filePatterns: list[str] = Field(default_factory=list)


# Directory-pattern → layer-name mapping for heuristic detection.
# Order matters: first match wins.
_LAYER_PATTERNS: list[dict[str, Any]] = [
    {
        "patterns": ["routes", "controller", "handler", "endpoint", "api"],
        "layerName": "API Layer",
        "description": "HTTP endpoints, route handlers, and API controllers",
    },
    {
        "patterns": ["service", "usecase", "use-case", "business"],
        "layerName": "Service Layer",
        "description": "Business logic and application services",
    },
    {
        "patterns": [
            "model", "entity", "schema", "database", "db", "migration",
            "repository", "repo",
        ],
        "layerName": "Data Layer",
        "description": "Data models, database access, and persistence",
    },
    {
        "patterns": ["component", "view", "page", "screen", "layout", "widget", "ui"],
        "layerName": "UI Layer",
        "description": "User interface components and views",
    },
    {
        "patterns": ["middleware", "interceptor", "guard", "filter", "pipe"],
        "layerName": "Middleware Layer",
        "description": "Request/response middleware and interceptors",
    },
    {
        "patterns": ["client", "integration", "external", "sdk", "vendor", "adapter"],
        "layerName": "External Services",
        "description": "External service integrations, SDKs, and third-party adapters",
    },
    {
        "patterns": [
            "worker", "job", "queue", "cron", "consumer", "processor",
            "scheduler", "background",
        ],
        "layerName": "Background Tasks",
        "description": "Background workers, job processors, and scheduled tasks",
    },
    {
        "patterns": ["util", "helper", "lib", "common", "shared"],
        "layerName": "Utility Layer",
        "description": "Shared utilities, helpers, and common libraries",
    },
    {
        "patterns": [
            "test", "spec", "__test__", "__spec__", "__tests__", "__specs__",
        ],
        "layerName": "Test Layer",
        "description": "Test files and test utilities",
    },
    {
        "patterns": ["config", "setting", "env"],
        "layerName": "Configuration Layer",
        "description": "Application configuration and environment settings",
    },
]


def _to_layer_id(name: str) -> str:
    """Convert a layer name to a kebab-case layer ID."""
    slug = re.sub(r"\s+", "-", name.lower())
    return f"layer:{slug}"


def _match_file_to_layer(file_path: str) -> str | None:
    """Determine which layer a file path belongs to via directory patterns.

    Returns the layer name or ``None`` if no pattern matches.
    """
    normalized_path = file_path.replace("\\", "/").lower()
    segments = normalized_path.split("/")

    for entry in _LAYER_PATTERNS:
        for segment in segments:
            for pattern in entry["patterns"]:
                if segment == pattern or segment == pattern + "s":
                    return entry["layerName"]
    return None


def detect_layers(graph: KnowledgeGraph) -> list[Layer]:
    """Heuristic layer detection — assign file nodes to layers by path pattern.

    Unmatched files (and file nodes without a ``filePath``) go to a "Core"
    layer. Only ``file``-type nodes are assigned.
    """
    layer_map: dict[str, list[str]] = {}

    for node in graph.nodes:
        if node.type != "file":
            continue
        if not node.filePath:
            continue
        layer_name = _match_file_to_layer(node.filePath) or "Core"
        layer_map.setdefault(layer_name, []).append(node.id)

    # Also catch file nodes without filePath
    for node in graph.nodes:
        if node.type != "file":
            continue
        if node.filePath:
            continue
        layer_map.setdefault("Core", []).append(node.id)

    layers: list[Layer] = []
    for name, node_ids in layer_map.items():
        if name == "Core":
            description = "Core application files"
        else:
            description = next(
                (
                    p["description"]
                    for p in _LAYER_PATTERNS
                    if p["layerName"] == name
                ),
                "",
            )
        layers.append(
            Layer(
                id=_to_layer_id(name),
                name=name,
                description=description,
                nodeIds=node_ids,
            )
        )
    return layers


def build_layer_detection_prompt(graph: KnowledgeGraph) -> str:
    """Build an LLM prompt asking the model to identify logical layers."""
    file_paths = [
        node.filePath
        for node in graph.nodes
        if node.type == "file" and node.filePath
    ]
    file_list_str = "\n".join(f"  - {f}" for f in file_paths)

    return f"""You are a software architecture analyst. Given the following list of file paths from a codebase, identify the logical architectural layers.

File paths:
{file_list_str}

Return a JSON array of 3-7 layers. Each layer object must have:
- "name": A short layer name (e.g., "API", "Data", "UI")
- "description": What this layer is responsible for (1 sentence)
- "filePatterns": An array of path prefixes that belong to this layer (e.g., ["src/routes/", "src/controllers/"])

Every file should belong to exactly one layer. Use the most specific pattern possible.

Respond ONLY with the JSON array, no additional text."""


def parse_layer_detection_response(response: str) -> list[LLMLayerResponse] | None:
    """Parse an LLM layer-detection response. Returns ``None`` on failure."""
    if not response or not response.strip():
        return None

    try:
        fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", response)
        json_str = fence_match.group(1).strip() if fence_match else response.strip()

        array_match = re.search(r"\[[\s\S]*\]", json_str)
        if not array_match:
            return None

        parsed: Any = json.loads(array_match.group(0))
    except (ValueError, TypeError):
        return None

    if not isinstance(parsed, list) or len(parsed) == 0:
        return None

    layers: list[LLMLayerResponse] = []
    for item in parsed:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        patterns = item.get("filePatterns")
        patterns_list = (
            [p for p in patterns if isinstance(p, str)]
            if isinstance(patterns, list)
            else []
        )
        layers.append(
            LLMLayerResponse(
                name=item["name"],
                description=item["description"]
                if isinstance(item.get("description"), str)
                else "",
                filePatterns=patterns_list,
            )
        )

    return layers if layers else None


def apply_llm_layers(
    graph: KnowledgeGraph,
    llm_layers: list[LLMLayerResponse],
) -> list[Layer]:
    """Apply LLM-provided layer definitions to a graph by path-prefix matching.

    Unassigned file nodes go to an "Other" layer; empty layers are skipped.
    """
    layer_map: dict[str, list[str]] = {}

    # Initialize all LLM layers (preserves order)
    for llm_layer in llm_layers:
        layer_map.setdefault(llm_layer.name, [])

    for node in graph.nodes:
        if node.type != "file":
            continue

        if not node.filePath:
            layer_map.setdefault("Other", []).append(node.id)
            continue

        normalized_path = node.filePath.replace("\\", "/")
        assigned = False

        for llm_layer in llm_layers:
            for pattern in llm_layer.filePatterns:
                if normalized_path.startswith(pattern) or (
                    "/" + pattern in normalized_path
                ):
                    layer_map[llm_layer.name].append(node.id)
                    assigned = True
                    break
            if assigned:
                break

        if not assigned:
            layer_map.setdefault("Other", []).append(node.id)

    descriptions = {layer.name: layer.description for layer in llm_layers}

    layers: list[Layer] = []
    for name, node_ids in layer_map.items():
        if not node_ids:
            continue
        layers.append(
            Layer(
                id=_to_layer_id(name),
                name=name,
                description=descriptions.get(name) or "Uncategorized files",
                nodeIds=node_ids,
            )
        )
    return layers
