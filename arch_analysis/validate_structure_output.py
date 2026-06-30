"""Validate ``extract_structure`` output against its schema and batch coverage.

Run by the file-analyzer immediately after ``extract_structure`` (Phase 1
Step 3). It guards against the silent failure modes the agent used to discover
only at merge time: a truncated/malformed results file, a ``filesAnalyzed``
count that disagrees with ``results``, duplicate per-file entries, non-integer
metrics, and batch files that were neither analyzed nor explicitly skipped.

Exit code is ``0`` when the output is valid, ``1`` otherwise (with every issue
printed to stderr). The file-analyzer retries extraction once on a non-zero
exit, then fails hard.

Usage:
    python -m arch_analysis.validate_structure_output <input.json> <extract-results.json>

``<input.json>`` is the ``extract_structure`` input (carries ``batchFiles``);
``<extract-results.json>`` is its output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .schema import SchemaValidationError, validate_structure_output


def check_structure_output(
    input_data: dict[str, Any],
    results_data: dict[str, Any],
) -> list[str]:
    """Return a list of issue strings; empty means the output is valid."""
    issues: list[str] = []

    try:
        validate_structure_output(results_data)
    except SchemaValidationError as err:
        # A schema failure is terminal — downstream checks assume the shape.
        return [f"schema validation failed: {err}"]

    results = results_data.get("results", [])
    files_analyzed = results_data.get("filesAnalyzed")
    files_skipped = results_data.get("filesSkipped", [])

    if files_analyzed != len(results):
        issues.append(
            f"filesAnalyzed ({files_analyzed!r}) does not match the number of "
            f"results ({len(results)})"
        )

    # Duplicate per-file results.
    seen: set[str] = set()
    for r in results:
        path = r.get("path")
        if path in seen:
            issues.append(f"duplicate result for path '{path}'")
        seen.add(path)

    # Malformed metrics — every value must be a non-negative integer count.
    for r in results:
        metrics = r.get("metrics")
        if not isinstance(metrics, dict):
            issues.append(f"result for '{r.get('path')}' has non-object metrics")
            continue
        for key, value in metrics.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                issues.append(
                    f"result for '{r.get('path')}' has malformed metric "
                    f"'{key}'={value!r} (expected a non-negative integer)"
                )

    # Batch coverage — every input file must be analyzed or explicitly skipped.
    covered = seen | {p for p in files_skipped if isinstance(p, str)}
    for f in input_data.get("batchFiles", []):
        if not isinstance(f, dict):
            continue
        path = f.get("path")
        if path not in covered:
            issues.append(
                f"batch file '{path}' is missing from results and was not skipped"
            )

    return issues


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        sys.stderr.write(
            "Usage: python -m arch_analysis.validate_structure_output "
            "<input.json> <extract-results.json>\n"
        )
        return 1

    input_path, results_path = Path(args[0]), Path(args[1])
    try:
        input_data = json.loads(input_path.read_text(encoding="utf-8"))
        results_data = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"validate_structure_output failed: cannot read input: {err}\n")
        return 1

    issues = check_structure_output(input_data, results_data)
    if issues:
        sys.stderr.write(
            f"validate_structure_output: {len(issues)} issue(s) found:\n"
        )
        for issue in issues:
            sys.stderr.write(f"  - {issue}\n")
        return 1

    sys.stderr.write(
        f"validate_structure_output: OK "
        f"({results_data.get('filesAnalyzed')} files analyzed, "
        f"{len(results_data.get('filesSkipped', []))} skipped)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
