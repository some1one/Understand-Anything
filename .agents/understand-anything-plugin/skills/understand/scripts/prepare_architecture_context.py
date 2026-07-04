#!/usr/bin/env python3
"""Prepare deterministic architecture-analyzer template arguments."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

FILE_LEVEL_TYPES = {
    "file", "config", "document", "service", "pipeline",
    "table", "schema", "resource", "endpoint",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_context_from_skill(skill_dir: Path, skill_name: str, names: list[str]) -> str:
    loader = skill_dir.parent / skill_name / "scripts" / "load_prompt.py"
    chunks: list[str] = []
    if not loader.is_file():
        return ""

    for name in names:
        result = subprocess.run(
            [sys.executable, str(loader), str(name)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            chunks.append(result.stdout)
    return "\n\n".join(chunks)


def compact_file_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "name": node.get("name"),
        "filePath": node.get("filePath"),
        "summary": node.get("summary"),
        "tags": node.get("tags", []),
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: prepare_architecture_context.py <project-root> <skill-dir>\n")
        return 1

    project_root = Path(args[0]).resolve()
    skill_dir = Path(args[1]).resolve()
    inter = project_root / ".understand-anything" / "intermediate"
    scan = load_json(inter / "scan-result.json")
    graph = load_json(inter / "assembled-graph.json")
    context = {}
    context_path = inter / "project-context.json"
    if context_path.is_file():
        context = load_json(context_path)

    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    edges = [e for e in graph.get("edges", []) if isinstance(e, dict)]
    file_nodes = [compact_file_node(n) for n in nodes if n.get("type") in FILE_LEVEL_TYPES]
    import_edges = [e for e in edges if e.get("type") == "imports"]

    payload = {
        "PROJECT_ROOT": str(project_root),
        "PROJECT_NAME": scan.get("name"),
        "PROJECT_DESCRIPTION": scan.get("description"),
        "FRAMEWORKS": scan.get("frameworks", []),
        "DIR_TREE": context.get("dirTree", []),
        "LANGUAGE_CONTEXT": load_context_from_skill(
            skill_dir, "understand-language", scan.get("languages", [])
        ),
        "FRAMEWORK_CONTEXT": load_context_from_skill(
            skill_dir, "understand-framework", scan.get("frameworks", [])
        ),
        "FILE_NODES_JSON": file_nodes,
        "IMPORT_EDGES_JSON": import_edges,
        "ALL_EDGES_JSON": edges,
        "PREVIOUS_LAYERS_JSON": graph.get("layers", []),
    }
    out_path = inter / "architecture-template-args.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(str(out_path) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
