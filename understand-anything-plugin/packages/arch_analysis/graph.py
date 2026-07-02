"""Import-graph analysis (sections C, E, F, K).

Deterministic graph analytics built on networkx, with numpy/scipy for the
fan-in/fan-out correlation and pandas for the inter-group matrix.
"""

from __future__ import annotations

from collections import Counter

import networkx as nx
import numpy as np
import pandas as pd
from scipy import stats

from .constants import MIN_FILES_FOR_CORRELATION
from .models import Edge


def build_import_graph(node_ids: list[str], import_edges: list[Edge]) -> nx.DiGraph:
    """Directed graph of file-import relationships (section C)."""
    known = set(node_ids)
    g = nx.DiGraph()
    g.add_nodes_from(node_ids)
    for e in import_edges:
        if e.source in known and e.target in known and e.source != e.target:
            g.add_edge(e.source, e.target)
    return g


def fan_in_out(graph: nx.DiGraph) -> tuple[dict[str, int], dict[str, int]]:
    """Per-file fan-in (importers) and fan-out (imports) counts (section C)."""
    fan_in = {n: int(graph.in_degree(n)) for n in graph.nodes}
    fan_out = {n: int(graph.out_degree(n)) for n in graph.nodes}
    return fan_in, fan_out


def inter_group_imports(
    import_edges: list[Edge], node_group: dict[str, str]
) -> list[dict]:
    """Count import edges between distinct directory groups (section E)."""
    counts: Counter[tuple[str, str]] = Counter()
    for e in import_edges:
        gs, gt = node_group.get(e.source), node_group.get(e.target)
        if gs is None or gt is None or gs == gt:
            continue
        counts[(gs, gt)] += 1
    return [
        {"from": a, "to": b, "count": n}
        for (a, b), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def intra_group_density(
    import_edges: list[Edge], node_group: dict[str, str], group_names: list[str]
) -> dict[str, dict]:
    """Internal vs. total import edges per group (section F).

    ``totalEdges`` counts every edge that involves the group (one endpoint is
    enough); ``internalEdges`` counts edges with both endpoints in the group.
    """
    internal: Counter[str] = Counter()
    total: Counter[str] = Counter()
    for e in import_edges:
        gs, gt = node_group.get(e.source), node_group.get(e.target)
        if gs is not None and gs == gt:
            internal[gs] += 1
            total[gs] += 1
            continue
        if gs is not None:
            total[gs] += 1
        if gt is not None:
            total[gt] += 1

    out: dict[str, dict] = {}
    for g in group_names:
        t, i = total.get(g, 0), internal.get(g, 0)
        out[g] = {
            "internalEdges": i,
            "totalEdges": t,
            "density": round(i / t, 4) if t else 0.0,
        }
    return out


def dependency_direction(inter_group: list[dict]) -> list[dict]:
    """Dominant import direction between each group pair (section K)."""
    counts = {(d["from"], d["to"]): d["count"] for d in inter_group}
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for a, b in counts:
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        ab, ba = counts.get((a, b), 0), counts.get((b, a), 0)
        if ab > ba:
            out.append({"dependent": a, "dependsOn": b})
        elif ba > ab:
            out.append({"dependent": b, "dependsOn": a})
        # ties are ambiguous -> omitted
    return out


def inter_group_matrix(inter_group: list[dict]) -> dict[str, dict[str, int]]:
    """Pivot the inter-group import counts into a dense matrix (pandas)."""
    if not inter_group:
        return {}
    df = pd.DataFrame(inter_group)
    pivot = df.pivot_table(
        index="from", columns="to", values="count", aggfunc="sum", fill_value=0
    )
    return {
        str(idx): {str(col): int(pivot.loc[idx, col]) for col in pivot.columns}
        for idx in pivot.index
    }


def graph_metrics(
    graph: nx.DiGraph, fan_in: dict[str, int], fan_out: dict[str, int]
) -> dict:
    """Whole-graph structural metrics, including a fan-in/out correlation.

    The Spearman correlation between fan-in and fan-out across files signals
    whether hub files tend to be both heavily imported and import-heavy.
    """
    n = graph.number_of_nodes()
    metrics: dict = {
        "fileCount": n,
        "importEdgeCount": graph.number_of_edges(),
        "density": round(nx.density(graph), 4) if n > 1 else 0.0,
        "weaklyConnectedComponents": (
            nx.number_weakly_connected_components(graph) if n else 0
        ),
        "isDag": bool(nx.is_directed_acyclic_graph(graph)) if n else True,
    }
    nodes = list(graph.nodes)
    if n >= MIN_FILES_FOR_CORRELATION:
        xi = np.array([fan_in[x] for x in nodes], dtype=float)
        xo = np.array([fan_out[x] for x in nodes], dtype=float)
        if xi.std() > 0 and xo.std() > 0:
            rho, p = stats.spearmanr(xi, xo)
            metrics["fanInFanOutSpearman"] = round(float(rho), 4)
            metrics["fanInFanOutPValue"] = round(float(p), 4)
    return metrics
