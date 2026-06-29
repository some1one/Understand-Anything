"""Cross-check the Phase 2 layer-assignment output.

Validates ``layers.json`` against the input file nodes, replacing the manual
"sum of nodeIds must equal totalFileNodes" check in the agent prompt.

Checks performed:
  1. Structural schema (``layers.schema.json``): id format ``layer:<kebab>``,
     required fields present, ``nodeIds`` non-empty.
  2. Layer count is within 3..10 and layer ids are unique.
  3. Every input file-node id appears in **exactly one** layer.
  4. No layer references a node id that is absent from the input (no invented
     ids), and no node id is assigned to more than one layer.

Usage::

    python -m arch_analysis.validate_layers <input.json> <layers.json>

Exit 0 if valid, 1 otherwise (problems printed to stderr).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import orjson

from .schema import SchemaValidationError, validate_layers as validate_layers_schema

MIN_LAYERS = 3
MAX_LAYERS = 10


def _input_node_ids(payload: dict) -> list[str]:
    return [n["id"] for n in payload.get("fileNodes", [])]


def check(input_payload: dict, layers: object) -> list[str]:
    """Return a list of problem strings; empty means the output is valid."""
    problems: list[str] = []

    # 1. Structural schema.
    try:
        validate_layers_schema(layers)
    except SchemaValidationError as exc:
        problems.append(f"schema: {exc}")
        # Without a well-formed array the remaining checks can't run.
        if not isinstance(layers, list):
            return problems

    assert isinstance(layers, list)

    # 2. Layer count + unique ids.
    if not (MIN_LAYERS <= len(layers) <= MAX_LAYERS):
        problems.append(
            f"layer count {len(layers)} is outside the allowed range "
            f"{MIN_LAYERS}..{MAX_LAYERS}"
        )
    layer_ids = [lyr.get("id") for lyr in layers]
    dup_layer_ids = [i for i, c in Counter(layer_ids).items() if c > 1]
    if dup_layer_ids:
        problems.append(f"duplicate layer ids: {sorted(map(str, dup_layer_ids))}")

    # 3 & 4. Node coverage.
    input_ids = _input_node_ids(input_payload)
    input_set = set(input_ids)

    assignment: Counter[str] = Counter()
    for lyr in layers:
        for nid in lyr.get("nodeIds", []):
            assignment[nid] += 1

    assigned_set = set(assignment)
    missing = sorted(input_set - assigned_set)
    invented = sorted(assigned_set - input_set)
    duplicated = sorted(nid for nid, c in assignment.items() if c > 1)

    if missing:
        problems.append(f"{len(missing)} input node(s) not assigned to any layer: {missing[:20]}")
    if invented:
        problems.append(f"{len(invented)} node id(s) not present in input (invented): {invented[:20]}")
    if duplicated:
        problems.append(f"{len(duplicated)} node id(s) assigned to multiple layers: {duplicated[:20]}")

    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: python -m arch_analysis.validate_layers <input.json> <layers.json>",
            file=sys.stderr,
        )
        return 1

    try:
        input_payload = orjson.loads(Path(args[0]).read_bytes())
        layers = orjson.loads(Path(args[1]).read_bytes())
    except Exception as exc:  # noqa: BLE001
        print(f"arch_analysis.validate_layers: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    problems = check(input_payload, layers)
    if problems:
        print("LAYER VALIDATION FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    total = len(_input_node_ids(input_payload))
    print(f"OK: {len(layers)} layers, all {total} input nodes assigned to exactly one layer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
