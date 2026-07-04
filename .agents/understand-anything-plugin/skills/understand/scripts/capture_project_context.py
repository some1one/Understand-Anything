#!/usr/bin/env python3
"""Capture deterministic project context for /understand subagent prompts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ENTRY_POINTS = [
    "src/index.ts",
    "src/main.ts",
    "src/App.tsx",
    "index.js",
    "main.py",
    "manage.py",
    "app.py",
    "wsgi.py",
    "asgi.py",
    "run.py",
    "__main__.py",
    "src/main.rs",
    "src/lib.rs",
    "Program.cs",
    "config.ru",
    "index.php",
]

MANIFESTS = ["package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml"]
READMES = ["README.md", "README.rst", "readme.md"]
IGNORED_PARTS = {"node_modules", ".git", "dist"}


def _read_first(root: Path, names: list[str], limit: int | None = None) -> str:
    for name in names:
        path = root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[:limit] if limit is not None else text
    return ""


def _dir_tree(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(out) >= 100:
            break
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) > 2 or any(part in IGNORED_PARTS for part in parts):
            continue
        if path.is_file():
            out.append(str(rel))
    return out


def _entry_point(root: Path) -> str | None:
    for rel in ENTRY_POINTS:
        if (root / rel).is_file():
            return rel
    for pattern in ("cmd/*/main.go", "src/main/java/**/Application.java"):
        matches = sorted(root.glob(pattern))
        if matches:
            return str(matches[0].relative_to(root))
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("Usage: capture_project_context.py <project-root>\n")
        return 1
    root = Path(args[0]).resolve()
    if not root.is_dir():
        sys.stderr.write(f"Not a directory: {root}\n")
        return 1
    payload = {
        "readmeContent": _read_first(root, READMES, limit=3000),
        "manifestContent": _read_first(root, MANIFESTS),
        "dirTree": _dir_tree(root),
        "entryPoint": _entry_point(root),
    }
    out_path = root / ".understand-anything" / "intermediate" / "project-context.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
