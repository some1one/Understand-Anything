"""Merge the selected partition graphs into ``intermediate/assembled-graph.json``.

Run mid-``/understand`` after every included part has been assembled into
``partitions/<part>.knowledge-graph.json``. It unifies them (dedup nodes/edges,
real nodes beating boundary stubs) so Phase 3–7 (assemble-review, architecture,
review, save) operate on one graph exactly as in a monolithic run.

Distinct from :mod:`understand_core.merge_subdomain_graphs`, which writes the
final ``knowledge-graph.json``; this writes the mid-pipeline assembled graph and
does not touch embeddings.

Usage:
    python -m understand_core.merge_parts <project-root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .merge_subdomain_graphs import load_graph, merge_graphs, select_partition_graphs


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write("Usage: python -m understand_core.merge_parts <project-root>\n")
        return 1

    project_root = Path(args[0]).resolve()
    graph_files = select_partition_graphs(project_root)
    if not graph_files:
        sys.stderr.write("No partition graphs found to merge\n")
        return 1

    graphs = []
    for f in graph_files:
        g = load_graph(f)
        if g is not None:
            graphs.append(g)
    if not graphs:
        sys.stderr.write("Error: no valid partition graphs loaded\n")
        return 1

    merged, report = merge_graphs(graphs)

    inter = project_root / ".understand-anything" / "intermediate"
    inter.mkdir(parents=True, exist_ok=True)
    out_path = inter / "assembled-graph.json"
    out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    for line in report:
        print(line, file=sys.stderr)
    print(f"\nMerged {len(graphs)} parts → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
