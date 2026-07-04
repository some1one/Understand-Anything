#!/usr/bin/env python3
"""Print one language prompt snippet by normalized language name."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALIASES = {
    "c": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "cplusplus": "cpp",
    "csharp": "csharp",
    "cs": "csharp",
    "csharpdotnet": "csharp",
    "dotnet": "csharp",
    "docker": "dockerfile",
    "dockerfile": "dockerfile",
    "golang": "go",
    "js": "javascript",
    "md": "markdown",
    "proto": "protobuf",
    "py": "python",
    "rb": "ruby",
    "rs": "rust",
    "sh": "shell",
    "bash": "shell",
    "zsh": "shell",
    "tf": "terraform",
    "ts": "typescript",
    "tsx": "typescript",
    "yml": "yaml",
}


def normalize(value: str) -> str:
    lowered = value.lower()
    if "#" in lowered:
        return "csharp"
    if "++" in lowered:
        return "cpp"
    key = re.sub(r"[^a-z0-9]+", "", lowered)
    return ALIASES.get(key, key)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].strip():
        sys.stderr.write("Usage: load_prompt.py <language>\n")
        return 2

    skill_dir = Path(__file__).resolve().parents[1]
    key = normalize(args[0])
    path = skill_dir / "prompts" / f"{key}.md"
    if not path.is_file():
        sys.stderr.write(f"No language prompt snippet found for: {args[0]}\n")
        return 1

    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
