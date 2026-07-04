#!/usr/bin/env python3
"""Print one framework prompt addendum by normalized framework name."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALIASES = {
    "expressjs": "express",
    "fastapi": "fastapi",
    "gin": "gin",
    "gingonic": "gin",
    "next": "nextjs",
    "nextjs": "nextjs",
    "rails": "rails",
    "rubyonrails": "rails",
    "reactjs": "react",
    "spring": "spring",
    "springboot": "spring",
    "vuejs": "vue",
}


def normalize(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", value.lower())
    return ALIASES.get(key, key)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].strip():
        sys.stderr.write("Usage: load_prompt.py <framework>\n")
        return 2

    skill_dir = Path(__file__).resolve().parents[1]
    key = normalize(args[0])
    path = skill_dir / "prompts" / f"{key}.md"
    if not path.is_file():
        sys.stderr.write(f"No framework prompt addendum found for: {args[0]}\n")
        return 1

    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
