"""Deterministic domain-graph validation.

Validates a domain knowledge graph (nodes of type ``domain``/``flow``/``step``)
using the shared :func:`arch_analysis.validate_graph.review_graph` checker,
which automatically relaxes the layers requirement for domain graphs. Adds a
domain-specific completeness check (at least one ``domain`` node).

Usage:
    python -m arch_analysis.validate_domain_graph <domain-graph.json> [review.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .validate_graph import review_graph


def review_domain_graph(graph: dict[str, Any]) -> dict[str, Any]:
    review = review_graph(graph)
    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []
    if not any(isinstance(n, dict) and n.get("type") == "domain" for n in nodes):
        review["issues"].append("Domain graph has zero 'domain' nodes")
    return review


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write(
            "Usage: python -m arch_analysis.validate_domain_graph "
            "<domain-graph.json> [review.json]\n"
        )
        return 1

    graph_path = Path(args[0])
    review_path = Path(args[1]) if len(args) > 1 else graph_path.with_name("domain-review.json")

    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"validate_domain_graph failed: cannot read {graph_path}: {err}\n")
        return 1

    review = review_domain_graph(graph)
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")

    sys.stderr.write(
        f"validate_domain_graph: {len(review['issues'])} issues, "
        f"{len(review['warnings'])} warnings\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
