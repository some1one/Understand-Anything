#!/usr/bin/env python3
"""Deterministic structural extraction (Python port of extract-structure.mjs).

Replaces ``skills/understand/extract-structure.mjs`` and the structural
extraction logic it delegated to in ``@understand-anything/core``
(TreeSitterPlugin + non-code parsers).

Usage::

    python -m arch_analysis.extract_structure <input.json> <output.json>

Input JSON::

    { "projectRoot": "/abs",
      "batchFiles": [{"path","language","sizeLines","fileCategory"}],
      "batchImportData": {"src/x.ts": ["src/y.ts"]} }

Output JSON::

    { "scriptCompleted": true, "filesAnalyzed": N, "filesSkipped": [...],
      "results": [ <per-file result> ] }

The per-file result shape and ``build_result`` semantics match the .mjs
``buildResult`` exactly (see the docstring on :func:`build_result`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .structure import StructuralAnalysis, analyze_file, extract_call_graph


def count_lines(content: str) -> tuple[int, int]:
    """Return ``(total_lines, non_empty_lines)`` with ``wc -l`` semantics.

    For content ending in ``\\n``, ``total_lines`` is ``len(lines) - 1``
    (the trailing empty element from ``split`` is not a line); otherwise it is
    ``len(lines)``. ``non_empty_lines`` counts lines with non-whitespace
    content. Mirrors the .mjs ``main()`` computation exactly.
    """
    lines = content.split("\n")
    total_lines = max(0, len(lines) - 1) if content.endswith("\n") else len(lines)
    non_empty_lines = sum(1 for line in lines if line.strip())
    return total_lines, non_empty_lines


def build_result(
    file: dict,
    total_lines: int,
    non_empty_lines: int,
    analysis: StructuralAnalysis | None,
    call_graph: list[dict] | None,
    batch_import_data: dict | None,
) -> dict:
    """Map a :class:`StructuralAnalysis` to the file-analyzer output schema.

    Faithful port of the .mjs ``buildResult``. Critical semantics:

    - ``language`` passes through unchanged from input (even if ``None``).
    - ``metrics.importCount``: use ``batch_import_data[path]`` ONLY when it is a
      non-empty list; otherwise fall back to counting the parser's RELATIVE
      imports (``source`` starting with ``.``), excluding external packages.
      An empty list in ``batch_import_data`` falls back (this is the JS
      "empty arrays are truthy" bug, reproduced intentionally).
    - Code arrays always yield their ``*Count`` metric (present-but-maybe-empty);
      non-code arrays yield a metric only when the parser populated them.
    - Fields that do not apply are omitted.
    """
    base: dict = {
        "path": file.get("path"),
        "language": file.get("language"),
        "fileCategory": file.get("fileCategory"),
        "totalLines": total_lines,
        "nonEmptyLines": non_empty_lines,
    }

    if analysis is None:
        base["metrics"] = {}
        return base

    if analysis.functions:
        base["functions"] = [
            {
                "name": fn["name"],
                "startLine": fn["lineRange"][0],
                "endLine": fn["lineRange"][1],
                "params": fn.get("params") or [],
            }
            for fn in analysis.functions
        ]

    if analysis.classes:
        base["classes"] = [
            {
                "name": cls["name"],
                "startLine": cls["lineRange"][0],
                "endLine": cls["lineRange"][1],
                "methods": cls.get("methods") or [],
                "properties": cls.get("properties") or [],
            }
            for cls in analysis.classes
        ]

    if analysis.exports:
        base["exports"] = [
            {
                "name": exp["name"],
                "line": exp["lineNumber"],
                "isDefault": exp.get("isDefault") is True,
            }
            for exp in analysis.exports
        ]

    if analysis.sections:
        base["sections"] = [
            {"heading": s["name"], "level": s["level"], "line": s["lineRange"][0]}
            for s in analysis.sections
        ]

    if analysis.definitions:
        base["definitions"] = [
            {
                "name": d["name"],
                "kind": d["kind"],
                "fields": d.get("fields") or [],
                "startLine": d["lineRange"][0],
                "endLine": d["lineRange"][1],
            }
            for d in analysis.definitions
        ]

    if analysis.services:
        services = []
        for s in analysis.services:
            entry = {"name": s["name"], "image": s.get("image"), "ports": s.get("ports") or []}
            if s.get("lineRange"):
                entry["startLine"] = s["lineRange"][0]
                entry["endLine"] = s["lineRange"][1]
            services.append(entry)
        base["services"] = services

    if analysis.endpoints:
        base["endpoints"] = [
            {
                "method": e.get("method"),
                "path": e["path"],
                "startLine": e["lineRange"][0],
                "endLine": e["lineRange"][1],
            }
            for e in analysis.endpoints
        ]

    if analysis.steps:
        base["steps"] = [
            {"name": s["name"], "startLine": s["lineRange"][0], "endLine": s["lineRange"][1]}
            for s in analysis.steps
        ]

    if analysis.resources:
        base["resources"] = [
            {
                "name": r["name"],
                "kind": r["kind"],
                "startLine": r["lineRange"][0],
                "endLine": r["lineRange"][1],
            }
            for r in analysis.resources
        ]

    if call_graph:
        base["callGraph"] = call_graph

    metrics: dict = {}

    import_paths = (batch_import_data or {}).get(file.get("path"))
    if import_paths:  # non-empty list only (empty list is falsy in Python AND falls back)
        metrics["importCount"] = len(import_paths)
    elif analysis.imports is not None:
        internal = [imp for imp in analysis.imports if (imp.get("source") or "").startswith(".")]
        metrics["importCount"] = len(internal)

    # Code arrays are always present on a StructuralAnalysis (may be empty), so
    # these counts are always emitted for code/parser results — matching the JS
    # ``if (analysis.x)`` presence checks.
    if analysis.exports is not None:
        metrics["exportCount"] = len(analysis.exports)
    if analysis.functions is not None:
        metrics["functionCount"] = len(analysis.functions)
    if analysis.classes is not None:
        metrics["classCount"] = len(analysis.classes)
    if analysis.sections is not None:
        metrics["sectionCount"] = len(analysis.sections)
    if analysis.definitions is not None:
        metrics["definitionCount"] = len(analysis.definitions)
    if analysis.services is not None:
        metrics["serviceCount"] = len(analysis.services)
    if analysis.endpoints is not None:
        metrics["endpointCount"] = len(analysis.endpoints)
    if analysis.steps is not None:
        metrics["stepCount"] = len(analysis.steps)
    if analysis.resources is not None:
        metrics["resourceCount"] = len(analysis.resources)

    base["metrics"] = metrics
    return base


def run(input_path: str, output_path: str) -> None:
    input_data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    project_root = input_data.get("projectRoot")
    batch_files = input_data.get("batchFiles")
    batch_import_data = input_data.get("batchImportData")

    if not project_root or not isinstance(batch_files, list):
        raise ValueError("Invalid input: must contain projectRoot and batchFiles array")

    results: list[dict] = []
    files_skipped: list[str] = []

    for file in batch_files:
        rel_path = file.get("path")
        absolute_path = Path(project_root) / rel_path

        try:
            content = absolute_path.read_text(encoding="utf-8")
        except OSError:
            files_skipped.append(rel_path)
            continue

        total_lines, non_empty_lines = count_lines(content)

        analysis: StructuralAnalysis | None = None
        try:
            analysis = analyze_file(rel_path, content)
        except Exception:
            # Degraded analysis: still include basic metrics.
            analysis = None

        call_graph: list[dict] | None = None
        if file.get("fileCategory") in ("code", "script"):
            try:
                cg = extract_call_graph(rel_path, content)
                if cg:
                    call_graph = [
                        {"caller": e["caller"], "callee": e["callee"], "lineNumber": e["lineNumber"]}
                        for e in cg
                    ]
            except Exception:
                pass

        results.append(
            build_result(file, total_lines, non_empty_lines, analysis, call_graph, batch_import_data)
        )

    output = {
        "scriptCompleted": True,
        "filesAnalyzed": len(results),
        "filesSkipped": files_skipped,
        "results": results,
    }

    out = Path(output_path)
    out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    if not out.exists():
        raise RuntimeError(f"output file missing after write: {output_path}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        sys.stderr.write("Usage: python -m arch_analysis.extract_structure <input.json> <output.json>\n")
        return 1
    try:
        run(args[0], args[1])
    except Exception as err:  # noqa: BLE001 - top-level CLI guard
        sys.stderr.write(f"extract_structure failed: {err}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
