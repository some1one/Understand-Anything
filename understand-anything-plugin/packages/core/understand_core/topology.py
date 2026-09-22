"""Cross-category, deployment, data-pipeline and documentation analysis.

Covers sections D (cross-category dependencies), H (deployment topology),
I (data pipeline) and J (documentation coverage).
"""

from __future__ import annotations

from collections import Counter

from .constants import (
    CI_DIR_SEGMENTS,
    CI_FILENAMES,
    DOC_EXTENSIONS,
    INFRA_DIR_SEGMENTS,
    INFRA_EXTENSIONS,
    SCHEMA_EXTENSIONS,
)
from .models import Edge, FileNode


def cross_category_edges(
    all_edges: list[Edge], node_type: dict[str, str]
) -> list[dict]:
    """Count edges between *different* node-type groups (section D)."""
    counts: Counter[tuple[str, str, str]] = Counter()
    for e in all_edges:
        ts, tt = node_type.get(e.source), node_type.get(e.target)
        if ts is None or tt is None or ts == tt:
            continue
        counts[(ts, tt, e.type)] += 1
    return [
        {"fromType": a, "toType": b, "edgeType": t, "count": n}
        for (a, b, t), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _segments(path: str) -> list[str]:
    return [p for p in path.replace("\\", "/").lower().split("/") if p]


def deployment_topology(nodes: list[FileNode]) -> dict:
    """Detect deployment / IaC / CI files and chains (section H)."""
    has = {"Dockerfile": False, "Compose": False, "K8s": False, "Terraform": False, "CI": False}
    infra: set[str] = set()

    for n in nodes:
        path = n.filePath.replace("\\", "/")
        base = n.basename
        blow = base.lower()
        segs = set(_segments(path))

        if base == "Dockerfile" or blow.startswith("dockerfile."):
            has["Dockerfile"] = True
            infra.add(path)
        elif blow.startswith("docker-compose"):
            has["Compose"] = True
            infra.add(path)
        elif path.lower().endswith(INFRA_EXTENSIONS):
            has["Terraform"] = True
            infra.add(path)
        elif (
            "workflows" in segs and ".github" in segs
            or base in CI_FILENAMES
            or segs & CI_DIR_SEGMENTS
        ):
            has["CI"] = True
            infra.add(path)
        elif segs & INFRA_DIR_SEGMENTS:
            has["K8s"] = True
            infra.add(path)

    return {
        "hasDockerfile": has["Dockerfile"],
        "hasCompose": has["Compose"],
        "hasK8s": has["K8s"],
        "hasTerraform": has["Terraform"],
        "hasCI": has["CI"],
        "infraFiles": sorted(infra),
    }


def data_pipeline(
    nodes: list[FileNode],
    node_group: dict[str, str],
    pattern_matches: dict[str, str],
) -> dict:
    """Identify schema -> migration -> model -> api data flow files (section I)."""
    data_groups = {g for g, lbl in pattern_matches.items() if lbl == "data"}
    api_groups = {g for g, lbl in pattern_matches.items() if lbl == "api"}

    schema: set[str] = set()
    migration: set[str] = set()
    model: set[str] = set()
    api: set[str] = set()

    for n in nodes:
        path = n.filePath.replace("\\", "/")
        low = path.lower()
        base = n.basename.lower()
        segs = set(_segments(path))

        is_schema = low.endswith(SCHEMA_EXTENSIONS) or base.startswith("schema.")
        is_migration = "migrations" in segs
        if is_schema:
            schema.add(path)
        if is_migration:
            migration.add(path)

        group = node_group.get(n.id)
        if not is_schema and not is_migration and (
            "models" in segs or group in data_groups
        ):
            model.add(path)
        if group in api_groups:
            api.add(path)

    return {
        "schemaFiles": sorted(schema),
        "migrationFiles": sorted(migration),
        "dataModelFiles": sorted(model),
        "apiHandlerFiles": sorted(api),
    }


def doc_coverage(
    directory_groups: dict[str, list[str]], nodes_by_id: dict[str, FileNode]
) -> dict:
    """Documentation coverage per directory group (section J)."""
    documented: set[str] = set()
    for group, ids in directory_groups.items():
        for nid in ids:
            node = nodes_by_id[nid]
            base = node.basename.lower()
            if node.type == "document" or base.endswith(DOC_EXTENSIONS):
                documented.add(group)
                break

    total = len(directory_groups)
    with_docs = len(documented)
    return {
        "groupsWithDocs": with_docs,
        "totalGroups": total,
        "coverageRatio": round(with_docs / total, 4) if total else 0.0,
        "undocumentedGroups": sorted(set(directory_groups) - documented),
    }
