"""Deterministic validation of the pre-layer assembled graph (Phase 3).

Runs after :mod:`arch_analysis.merge_batch_graphs` and before the
architecture-analyzer assigns layers, so :mod:`arch_analysis.validate_graph`'s
layer requirements do not yet apply. It reuses
:func:`arch_analysis.validate_graph.review_graph` with ``require_layers=False``
to check everything else the schema/contract demands — node & edge required
fields and enums (per ``graph-fragment.schema.json``), referential integrity,
uniqueness, self-edges, orphans, generic summaries, expected non-code edges,
and type/ID-prefix consistency.

With ``--scan-result`` it also cross-checks coverage: every scanned file should
have a node, and no node should reference a file outside the scan inventory.

Always exits ``0`` unless the graph file cannot be read; the review payload
(``scriptCompleted``, ``issues``, ``warnings``, ``stats``) is written to the
output path so the assemble-reviewer can act on it.

Usage:
    python -m arch_analysis.validate_assembled_graph <graph.json> <review.json>
        [--scan-result <scan-result.json>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .validate_graph import add_scan_coverage, load_scanned_paths, review_graph


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    positional: list[str] = []
    scan_result: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--scan-result" and i + 1 < len(args):
            scan_result = args[i + 1]
            i += 2
            continue
        if arg.startswith("--scan-result="):
            scan_result = arg.split("=", 1)[1]
            i += 1
            continue
        positional.append(arg)
        i += 1

    if len(positional) < 2:
        sys.stderr.write(
            "Usage: python -m arch_analysis.validate_assembled_graph "
            "<graph.json> <review.json> [--scan-result <scan-result.json>]\n"
        )
        return 1

    graph_path, review_path = positional[0], positional[1]
    try:
        graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(
            f"validate_assembled_graph failed: cannot read {graph_path}: {err}\n"
        )
        return 1

    review = review_graph(graph, require_layers=False)
    if scan_result is not None:
        try:
            add_scan_coverage(review, graph, load_scanned_paths(Path(scan_result)))
        except (OSError, json.JSONDecodeError) as err:
            sys.stderr.write(
                f"validate_assembled_graph: scan-coverage skipped — "
                f"cannot read {scan_result}: {err}\n"
            )

    Path(review_path).write_text(
        json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    cov = review["stats"].get("coverage")
    cov_note = (
        f", {cov['missingFileNodes']} scanned files with no node" if cov else ""
    )
    sys.stderr.write(
        f"validate_assembled_graph: {len(review['issues'])} issues, "
        f"{len(review['warnings'])} warnings "
        f"({review['stats']['totalNodes']} nodes, {review['stats']['totalEdges']} edges"
        f"{cov_note})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
