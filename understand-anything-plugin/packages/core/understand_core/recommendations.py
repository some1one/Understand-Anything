"""Automatable Phase 2 signals.

Several Phase 2 steps are mechanical: applying pattern labels to groups,
ranking groups by dependency direction, deciding which non-code layers the
threshold rules warrant, and producing a default file->layer assignment. These
don't need LLM judgement — they're computed here and surfaced in the analyzer
output so the agent can use them directly instead of guessing.

The LLM is still responsible for the genuinely semantic work: naming/merging
layers, writing project-specific descriptions, and disambiguating files in flat
or ambiguous groups (Phase 2, Step 4).
"""

from __future__ import annotations

from collections import Counter

import networkx as nx

from .constants import (
    FILE_PATTERN_LAYER_OVERRIDE,
    MIN_CONFIGS_FOR_LAYER,
    MIN_DOCS_FOR_LAYER,
    NODE_TYPE_LAYER,
    ROOT_GROUP,
)
from .models import FileNode


def _kebab(name: str) -> str:
    out = []
    for ch in name.strip().lower():
        out.append(ch if ch.isalnum() else "-")
    return "-".join(filter(None, "".join(out).split("-"))) or ROOT_GROUP


def _group_io(inter_group: list[dict]) -> tuple[Counter, Counter]:
    """Group-level import fan-in / fan-out from inter-group edge counts."""
    gin: Counter[str] = Counter()
    gout: Counter[str] = Counter()
    for e in inter_group:
        gout[e["from"]] += e["count"]
        gin[e["to"]] += e["count"]
    return gin, gout


def _group_roles(group_names: list[str], gin: Counter, gout: Counter) -> dict[str, dict]:
    """Classify each group's position in the dependency hierarchy."""
    roles: dict[str, dict] = {}
    for g in group_names:
        i, o = gin.get(g, 0), gout.get(g, 0)
        if i == 0 and o == 0:
            role = "isolated"
        elif o == 0:
            role = "foundational"  # imported by others, imports nothing
        elif i == 0:
            role = "top"  # imports others, imported by nothing
        elif i >= o:
            role = "foundational-leaning"
        else:
            role = "consumer"
        roles[g] = {"importedBy": i, "imports": o, "role": role}
    return roles


def _suggested_layer_by_group(pattern_matches: dict[str, str]) -> dict[str, str]:
    """Map each pattern-matched group to its layer id (Step 1, automated)."""
    return {g: f"layer:{label}" for g, label in pattern_matches.items()}


def _topological_order(
    group_names: list[str], gin: Counter, gout: Counter, direction: list[dict]
) -> list[str]:
    """Order groups foundational-first using the dependency direction (Step 2)."""
    graph = nx.DiGraph()
    graph.add_nodes_from(group_names)
    for d in direction:
        # foundational (dependsOn) -> consumer (dependent)
        if d["dependsOn"] in graph and d["dependent"] in graph:
            graph.add_edge(d["dependsOn"], d["dependent"])
    if nx.is_directed_acyclic_graph(graph):
        return list(nx.topological_sort(graph))
    # Cyclic: fall back to ranking by net "imported-by minus imports".
    return sorted(group_names, key=lambda g: gin.get(g, 0) - gout.get(g, 0), reverse=True)


def _non_code_layer_suggestions(
    node_type_groups: dict[str, list[str]],
    nodes_by_id: dict[str, FileNode],
    topology: dict,
    data_pipeline_info: dict,
) -> list[dict]:
    """Apply the deterministic Step 3 threshold rules for non-code layers."""
    suggestions: list[dict] = []

    def add(layer_id: str, node_ids: list[str], recommended: bool, reason: str) -> None:
        suggestions.append(
            {
                "layerId": layer_id,
                "recommended": recommended,
                "reason": reason,
                "nodeIds": sorted(node_ids),
            }
        )

    infra_ids = node_type_groups.get("service", []) + node_type_groups.get("resource", [])
    has_iac = any(
        topology.get(k)
        for k in ("hasDockerfile", "hasCompose", "hasK8s", "hasTerraform")
    )
    add(
        "layer:infrastructure",
        infra_ids,
        bool(infra_ids) or has_iac,
        f"{len(infra_ids)} infra node(s); IaC files detected={has_iac}",
    )

    ci_ids = node_type_groups.get("pipeline", [])
    add(
        "layer:ci-cd",
        ci_ids,
        bool(ci_ids) or bool(topology.get("hasCI")),
        f"{len(ci_ids)} pipeline node(s); CI detected={bool(topology.get('hasCI'))}",
    )

    doc_ids = node_type_groups.get("document", [])
    add(
        "layer:documentation",
        doc_ids,
        len(doc_ids) >= MIN_DOCS_FOR_LAYER,
        f"{len(doc_ids)} document node(s) (threshold {MIN_DOCS_FOR_LAYER})",
    )

    data_ids = (
        node_type_groups.get("table", [])
        + node_type_groups.get("schema", [])
        + node_type_groups.get("endpoint", [])
    )
    has_schema = bool(data_pipeline_info.get("schemaFiles"))
    add(
        "layer:data",
        data_ids,
        bool(data_ids) or has_schema,
        f"{len(data_ids)} data node(s); schema files detected={has_schema}",
    )

    config_ids = node_type_groups.get("config", [])
    non_pkg = [
        nid for nid in config_ids if nodes_by_id[nid].basename.lower() != "package.json"
    ]
    add(
        "layer:config",
        config_ids,
        len(non_pkg) >= MIN_CONFIGS_FOR_LAYER,
        f"{len(non_pkg)} config node(s) beyond package.json (threshold {MIN_CONFIGS_FOR_LAYER})",
    )

    return suggestions


def _default_layer_assignment(
    nodes: list[FileNode],
    node_group: dict[str, str],
    node_type: dict[str, str],
    file_patterns: dict[str, str],
    suggested_layer_by_group: dict[str, str],
) -> dict[str, str]:
    """Mechanical Step 6 starting assignment: node id -> layer id.

    Non-code nodes follow their node type; code files prefer a file-level
    pattern override, then their directory group's suggested layer, then a
    layer derived from the group name. The agent refines ambiguous cases.
    """
    assignment: dict[str, str] = {}
    for n in nodes:
        ntype = node_type[n.id]
        if ntype in NODE_TYPE_LAYER:
            assignment[n.id] = NODE_TYPE_LAYER[ntype]
            continue
        override = FILE_PATTERN_LAYER_OVERRIDE.get(file_patterns.get(n.id, ""))
        if override:
            assignment[n.id] = override
            continue
        group = node_group.get(n.id, ROOT_GROUP)
        assignment[n.id] = suggested_layer_by_group.get(group) or f"layer:{_kebab(group)}"
    return assignment


def phase2_recommendations(
    *,
    nodes: list[FileNode],
    nodes_by_id: dict[str, FileNode],
    node_group: dict[str, str],
    node_type: dict[str, str],
    node_type_groups: dict[str, list[str]],
    group_names: list[str],
    pattern_matches: dict[str, str],
    file_patterns: dict[str, str],
    inter_group: list[dict],
    direction: list[dict],
    topology: dict,
    data_pipeline_info: dict,
) -> dict:
    """Assemble all automatable Phase 2 signals into one block."""
    gin, gout = _group_io(inter_group)
    suggested = _suggested_layer_by_group(pattern_matches)
    return {
        "groupRoles": _group_roles(group_names, gin, gout),
        "suggestedLayerByGroup": suggested,
        "topologicalOrder": _topological_order(group_names, gin, gout, direction),
        "nonCodeLayerSuggestions": _non_code_layer_suggestions(
            node_type_groups, nodes_by_id, topology, data_pipeline_info
        ),
        "defaultLayerAssignment": _default_layer_assignment(
            nodes, node_group, node_type, file_patterns, suggested
        ),
    }
