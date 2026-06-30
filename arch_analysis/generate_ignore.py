"""Generate a starter ``.understandignore`` for a target project.

Python port of ``@understand-anything/core``'s ``generateStarterIgnoreFile``
(``ignore-generator.ts``) plus the ``generate-ignore.mjs`` CLI wrapper. All
suggestions are emitted commented-out — this is a one-time generation.

Usage:
    python -m arch_analysis.generate_ignore <projectRoot>

Exits 0 with a stderr notice if the target file already exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .languages import DEFAULT_IGNORE_PATTERNS

_HEADER = """# .understandignore — patterns for files/dirs to exclude from analysis
# Syntax: same as .gitignore (globs, # comments, ! negation, trailing / for dirs)
# Lines below are suggestions — uncomment to activate.
# Use ! prefix to force-include something excluded by defaults.
#
# Built-in defaults (always excluded unless negated):
#   node_modules/, .git/, dist/, build/, obj/, *.lock, *.min.js, etc.
#
"""

# Directory names matched case-insensitively against the on-disk entry name.
_EXACT_DIR_NAMES = [
    "__tests__",
    "test",
    "tests",
    "fixtures",
    "testdata",
    "docs",
    "examples",
    "scripts",
    "migrations",
    ".storybook",
    "unittests",
    "integrationtests",
]

# Directory-name suffixes matched case-insensitively via endswith.
_SUFFIX_DIR_GLOBS = [".tests", ".unittests", ".integrationtests"]

# Test file patterns grouped by language.
_TEST_PATTERN_GROUPS: list[tuple[str, list[str]]] = [
    ("JS / TS", ["*.test.*", "*.spec.*", "*.snap"]),
    ("C# / .NET", ["**/*Tests.cs", "**/*Test.cs", "**/*Fixture.cs", "**/*.Tests.csproj"]),
    ("Java / Kotlin", ["**/src/test/**", "**/*Test.java", "**/*IT.java", "**/*Spec.kt"]),
    ("Go", ["**/*_test.go"]),
]


def _parse_gitignore_patterns(gitignore_path: Path) -> list[str]:
    if not gitignore_path.exists():
        return []
    content = gitignore_path.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in content.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]


def _is_covered_by_defaults(pattern: str) -> bool:
    def normalize(p: str) -> str:
        return p.rstrip("/")

    normalized = normalize(pattern)
    return any(normalize(d) == normalized for d in DEFAULT_IGNORE_PATTERNS)


def _detect_directories(project_root: Path) -> list[str]:
    try:
        entries = list(project_root.iterdir())
    except OSError:
        return []
    matches: list[str] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        lower = entry.name.lower()
        if lower in _EXACT_DIR_NAMES:
            matches.append(f"{entry.name}/")
            continue
        if any(lower.endswith(suffix) for suffix in _SUFFIX_DIR_GLOBS):
            matches.append(f"{entry.name}/")
    return matches


def generate_starter_ignore_file(project_root: str | Path) -> str:
    """Generate starter .understandignore content for ``project_root``."""
    root = Path(project_root)
    sections: list[str] = [_HEADER]

    gitignore_patterns = [
        p
        for p in _parse_gitignore_patterns(root / ".gitignore")
        if not _is_covered_by_defaults(p)
    ]
    if gitignore_patterns:
        sections.append("# --- From .gitignore (uncomment to exclude) ---\n")
        for pattern in gitignore_patterns:
            sections.append(f"# {pattern}")
        sections.append("")

    detected = _detect_directories(root)
    if detected:
        sections.append("# --- Detected directories (uncomment to exclude) ---\n")
        for pattern in detected:
            sections.append(f"# {pattern}")
        sections.append("")

    sections.append("# --- Test file patterns (uncomment to exclude) ---\n")
    for label, patterns in _TEST_PATTERN_GROUPS:
        sections.append(f"# {label}")
        for pattern in patterns:
            sections.append(f"# {pattern}")
    sections.append("")

    return "\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    project_root = Path(args[0]).resolve() if args else Path.cwd()
    out_dir = project_root / ".understand-anything"
    out_path = out_dir / ".understandignore"

    if out_path.exists():
        sys.stderr.write(f"generate-ignore: {out_path} already exists — skipping\n")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate_starter_ignore_file(project_root), encoding="utf-8")
    sys.stderr.write(f"generate-ignore: wrote {out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
