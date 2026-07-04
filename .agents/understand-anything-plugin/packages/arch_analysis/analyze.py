"""CLI orchestrator for the Phase 1 structural analysis.

Reads the architecture-analyzer input JSON, runs every deterministic
computation (sections A--K plus extra graph metrics), validates the result
against the output contract, and writes it to disk.

Usage::

    python -m arch_analysis.analyze <input.json> <results.json>
    pdm run analyze <input.json> <results.json>

Exit 0 on success, exit 1 on fatal error (message printed to stderr).
"""

from __future__ import annotations

import sys
from pathlib import Path

import orjson

from .graph import (
    build_import_graph,
    dependency_direction,
    fan_in_out,
    graph_metrics,
    inter_group_imports,
    inter_group_matrix,
    intra_group_density,
)
from .grouping import group_by_directory, group_by_node_type, node_to_group
from .models import AnalysisInput, AnalysisResult
from .patterns import classify_all_files, match_directory_patterns
from .recommendations import phase2_recommendations
from .schema import validate_input, validate_output
from .topology import (
    cross_category_edges,
    data_pipeline,
    deployment_topology,
    doc_coverage,
)


def analyze(data: AnalysisInput) -> dict:
    """Run the full structural analysis and return the validated result dict."""
    nodes = data.fileNodes
    nodes_by_id = {n.id: n for n in nodes}
    node_ids = list(nodes_by_id)

    # A & B -- grouping
    directory_groups, common_prefix = group_by_directory(nodes)
    node_type_groups = group_by_node_type(nodes)
    node_group = node_to_group(directory_groups)
    node_type = {n.id: n.type for n in nodes}
    group_names = list(directory_groups)

    # C -- import adjacency / fan-in / fan-out
    graph = build_import_graph(node_ids, data.importEdges)
    fan_in, fan_out = fan_in_out(graph)

    # D -- cross-category dependency
    cross_cat = cross_category_edges(data.allEdges, node_type)

    # E, F, K -- inter-group, density, direction
    inter_group = inter_group_imports(data.importEdges, node_group)
    density = intra_group_density(data.importEdges, node_group, group_names)
    direction = dependency_direction(inter_group)

    # G -- pattern matching (directory + file level)
    pattern_matches = match_directory_patterns(group_names)
    file_patterns = classify_all_files(nodes)

    # H, I, J -- topology, pipeline, docs
    topology = deployment_topology(nodes)
    pipeline = data_pipeline(nodes, node_group, pattern_matches)
    docs = doc_coverage(directory_groups, nodes_by_id)

    result = {
        "scriptCompleted": True,
        "directoryGroups": directory_groups,
        "nodeTypeGroups": node_type_groups,
        "crossCategoryEdges": cross_cat,
        "interGroupImports": inter_group,
        "intraGroupDensity": density,
        "patternMatches": pattern_matches,
        "deploymentTopology": topology,
        "dataPipeline": pipeline,
        "docCoverage": docs,
        "dependencyDirection": direction,
        "fileStats": {
            "totalFileNodes": len(nodes),
            "filesPerGroup": {g: len(ids) for g, ids in directory_groups.items()},
            "nodeTypeCounts": {t: len(ids) for t, ids in node_type_groups.items()},
        },
        "fileFanIn": fan_in,
        "fileFanOut": fan_out,
        # --- extra deterministic signals (allowed by the contract) ---
        "commonPathPrefix": "/".join(common_prefix),
        "filePatternMatches": file_patterns,
        "interGroupMatrix": inter_group_matrix(inter_group),
        "graphMetrics": graph_metrics(graph, fan_in, fan_out),
        "phase2Recommendations": phase2_recommendations(
            nodes=nodes,
            nodes_by_id=nodes_by_id,
            node_group=node_group,
            node_type=node_type,
            node_type_groups=node_type_groups,
            group_names=group_names,
            pattern_matches=pattern_matches,
            file_patterns=file_patterns,
            inter_group=inter_group,
            direction=direction,
            topology=topology,
            data_pipeline_info=pipeline,
        ),
    }

    # Validate against the output contract (pydantic) and the published JSON
    # Schema file before returning.
    dumped = AnalysisResult.model_validate(result).model_dump()
    validate_output(dumped)
    return dumped


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: python -m arch_analysis.analyze <input.json> <results.json>",
            file=sys.stderr,
        )
        return 1

    input_path, output_path = Path(args[0]), Path(args[1])
    try:
        payload = orjson.loads(input_path.read_bytes())
        validate_input(payload)
        data = AnalysisInput.model_validate(payload)
        result = analyze(data)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(orjson.dumps(result, option=orjson.OPT_INDENT_2))
    except Exception as exc:  # noqa: BLE001 -- surface any failure to stderr
        print(f"arch_analysis: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
