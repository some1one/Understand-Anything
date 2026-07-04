"""Pre-deterministic seeding for a file-analyzer batch.

Generates the deterministic skeleton of a batch's knowledge-graph fragment
*before* the LLM applies semantic judgement:

  - **File nodes** — one per batch file whose node type/id is unambiguous
    (code/script/markup → ``file``, ``config``, ``document``, infra
    service/pipeline/resource, schema-definition data files).
  - **Function / class nodes** — significant definitions from the extraction
    results (10+ line functions, 2+ method or 20+ line classes, or anything
    exported), with deterministic ids and line ranges.
  - **Deterministic metadata** — summaries, complexity, and baseline tags the
    finalizer will require the LLM to preserve or enrich.
  - **Deterministic edges** — exact ``imports`` (1:1 from ``batchImportData``),
    ``contains`` (file → each definition node), and ``exports`` (file → each
    exported definition node).

The LLM may load this seed as its draft, then enrich summaries, tags, and
semantic edges. The seed is already a valid graph fragment once the optional
``batchIndex`` wrapper is stripped, so fully deterministic runs can finalize it
without an extra draft-enrichment step. :mod:`arch_analysis.finalize_file_batch_output`
verifies nothing seeded was dropped.

Usage:
    python -m arch_analysis.seed_file_batch_graph <context.json> <extract-results.json> <seed.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .file_graph import basename, deterministic_tags, file_level_node

# Significance thresholds (mirror file-analyzer.md Step 2).
_MIN_FUNCTION_LINES = 10
_MIN_CLASS_LINES = 20
_MIN_CLASS_METHODS = 2


def _line_span(start: Any, end: Any) -> int:
    if isinstance(start, int) and isinstance(end, int) and end >= start:
        return end - start + 1
    return 0


def _complexity(non_empty_lines: int) -> str:
    if non_empty_lines > 200:
        return "complex"
    if non_empty_lines >= 50:
        return "moderate"
    return "simple"


def _unique_tags(*groups: list[str]) -> list[str]:
    tags: list[str] = []
    for group in groups:
        for tag in group:
            if tag and tag not in tags:
                tags.append(tag)
    for tag in ("analysis", "project-structure", "codebase"):
        if len(tags) >= 3:
            break
        if tag not in tags:
            tags.append(tag)
    return tags[:5]


def _category_tags(node_type: str, category: str | None, path: str, language: str) -> list[str]:
    tags: list[str]
    if node_type == "document":
        tags = ["documentation", "reference", "project-knowledge"]
    elif node_type == "config":
        tags = ["configuration", "build-system", "project-settings"]
    elif node_type in {"service", "pipeline", "resource"}:
        tags = ["infrastructure", "automation", "deployment"]
    elif node_type == "schema":
        tags = ["schema-definition", "data-model", "validation"]
    else:
        tags = ["source-code", language or "unknown-language", "implementation"]

    lower = path.lower()
    if lower.endswith(".sh") or category == "script":
        tags.append("script")
    if "arch_analysis" in lower:
        tags.append("architecture-analysis")
    if "dashboard" in lower:
        tags.append("dashboard")
    if "skill" in lower:
        tags.append("skill")
    return tags


def _file_summary(path: str, node_type: str, language: str, result: dict[str, Any] | None) -> str:
    metrics = (result or {}).get("metrics") or {}
    functions = int(metrics.get("functionCount") or 0)
    classes = int(metrics.get("classCount") or 0)
    imports = int(metrics.get("importCount") or 0)

    if node_type == "document":
        return f"Documentation file covering project guidance or reference material for {path}."
    if node_type == "config":
        return f"Configuration file that controls project tooling or package behavior for {path}."
    if node_type in {"service", "pipeline", "resource"}:
        return f"Infrastructure or automation file defining build, deployment, or operational behavior for {path}."
    if node_type == "schema":
        return f"Schema file defining structured data or API contracts for {path}."

    details: list[str] = []
    if functions:
        details.append(f"{functions} function{'s' if functions != 1 else ''}")
    if classes:
        details.append(f"{classes} class{'es' if classes != 1 else ''}")
    if imports:
        details.append(f"{imports} internal import{'s' if imports != 1 else ''}")
    lang = language.title() if language else "Source"
    if details:
        return f"{lang} file {path} with " + ", ".join(details) + " identified by structural extraction."
    return f"{lang} file {path} represented as part of the project implementation graph."


def _symbol_summary(kind: str, name: str, path: str) -> str:
    return f"{kind.title()} {name} defined in {path}, included because structural extraction marked it significant for the file graph."


def _result_language(result: dict[str, Any] | None, path: str) -> str:
    language = (result or {}).get("language")
    if isinstance(language, str) and language:
        return language
    suffix = Path(path).suffix.lstrip(".")
    return suffix or "unknown"


def _non_empty_lines(result: dict[str, Any] | None) -> int:
    value = (result or {}).get("nonEmptyLines")
    return value if isinstance(value, int) else 0


def build_seed(
    context: dict[str, Any],
    extract_results: dict[str, Any],
) -> dict[str, Any]:
    """Return the deterministic seed fragment for a batch."""
    batch_index = context.get("batchIndex")
    batch_files = context.get("batchFiles", [])
    batch_import_data = context.get("batchImportData", {}) or {}

    results_by_path: dict[str, dict[str, Any]] = {}
    for r in extract_results.get("results", []):
        if isinstance(r, dict) and isinstance(r.get("path"), str):
            results_by_path[r["path"]] = r

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_keys: set[tuple[str, str, str]] = set()

    # Map each file path to its seeded file-node id (for contains/exports edges).
    file_node_id_by_path: dict[str, str] = {}

    def add_node(node: dict[str, Any]) -> bool:
        if node["id"] in node_ids:
            return False
        node_ids.add(node["id"])
        nodes.append(node)
        return True

    def add_edge(source: str, target: str, etype: str, weight: float) -> None:
        key = (source, target, etype)
        if source == target or key in edge_keys:
            return
        edge_keys.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "type": etype,
                "direction": "forward",
                "weight": weight,
            }
        )

    # ── File-level nodes ──────────────────────────────────────────────────
    for f in batch_files:
        if not isinstance(f, dict):
            continue
        path = f.get("path")
        if not isinstance(path, str):
            continue
        category = f.get("fileCategory")
        result = results_by_path.get(path)
        language = _result_language(result, path)
        typed = file_level_node(category, path)
        if typed is None:
            continue  # data sub-node files — deferred to the LLM.
        node_type, node_id = typed
        file_node_id_by_path[path] = node_id
        add_node(
            {
                "id": node_id,
                "type": node_type,
                "name": basename(path),
                "filePath": path,
                "summary": _file_summary(path, node_type, language, result),
                "tags": _unique_tags(
                    deterministic_tags(category, path),
                    _category_tags(node_type, category, path, language),
                ),
                "complexity": _complexity(_non_empty_lines(result)),
            }
        )

    # ── Function / class nodes + contains/exports edges (code files) ─────
    for path, file_id in file_node_id_by_path.items():
        if not file_id.startswith("file:"):
            continue  # only code files carry function/class sub-nodes
        result = results_by_path.get(path)
        if not result:
            continue
        exported_names = {
            e.get("name")
            for e in result.get("exports", [])
            if isinstance(e, dict) and e.get("name")
        }

        for fn in result.get("functions", []):
            if not isinstance(fn, dict) or not fn.get("name"):
                continue
            name = fn["name"]
            span = _line_span(fn.get("startLine"), fn.get("endLine"))
            significant = span >= _MIN_FUNCTION_LINES or name in exported_names
            if not significant:
                continue
            node_id = f"function:{path}:{name}"
            node = {
                "id": node_id,
                "type": "function",
                "name": name,
                "filePath": path,
                "summary": _symbol_summary("function", name, path),
                "tags": _unique_tags(["function"], _category_tags("file", "code", path, result.get("language", ""))),
                "complexity": _complexity(span),
            }
            if isinstance(fn.get("startLine"), int) and isinstance(fn.get("endLine"), int):
                node["lineRange"] = [fn["startLine"], fn["endLine"]]
            if add_node(node):
                add_edge(file_id, node_id, "contains", 1.0)
                if name in exported_names:
                    add_edge(file_id, node_id, "exports", 0.8)

        for cls in result.get("classes", []):
            if not isinstance(cls, dict) or not cls.get("name"):
                continue
            name = cls["name"]
            methods = cls.get("methods") or []
            span = _line_span(cls.get("startLine"), cls.get("endLine"))
            significant = (
                len(methods) >= _MIN_CLASS_METHODS
                or span >= _MIN_CLASS_LINES
                or name in exported_names
            )
            if not significant:
                continue
            node_id = f"class:{path}:{name}"
            node = {
                "id": node_id,
                "type": "class",
                "name": name,
                "filePath": path,
                "summary": _symbol_summary("class", name, path),
                "tags": _unique_tags(["class"], _category_tags("file", "code", path, result.get("language", ""))),
                "complexity": _complexity(span),
            }
            if isinstance(cls.get("startLine"), int) and isinstance(cls.get("endLine"), int):
                node["lineRange"] = [cls["startLine"], cls["endLine"]]
            if add_node(node):
                add_edge(file_id, node_id, "contains", 1.0)
                if name in exported_names:
                    add_edge(file_id, node_id, "exports", 0.8)

    # ── Exact imports edges (1:1 from batchImportData) ──────────────────
    for src_path, targets in batch_import_data.items():
        src_id = file_node_id_by_path.get(src_path)
        if src_id is None or not src_id.startswith("file:"):
            continue
        if not isinstance(targets, list):
            continue
        for tgt_path in targets:
            if not isinstance(tgt_path, str) or not tgt_path:
                continue
            # Targets may be cross-batch; emit `file:<target>` regardless.
            add_edge(src_id, f"file:{tgt_path}", "imports", 0.7)

    return {"batchIndex": batch_index, "nodes": nodes, "edges": edges}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 3:
        sys.stderr.write(
            "Usage: python -m arch_analysis.seed_file_batch_graph "
            "<context.json> <extract-results.json> <seed.json>\n"
        )
        return 1

    context_path, results_path, seed_path = (Path(args[0]), Path(args[1]), Path(args[2]))
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
        extract_results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"seed_file_batch_graph failed: cannot read input: {err}\n")
        return 1

    seed = build_seed(context, extract_results)
    seed_path.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")

    n_imports = sum(1 for e in seed["edges"] if e["type"] == "imports")
    sys.stderr.write(
        f"seed_file_batch_graph: batch {seed['batchIndex']} → "
        f"{len(seed['nodes'])} nodes, {len(seed['edges'])} edges "
        f"({n_imports} imports) written to {seed_path}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
