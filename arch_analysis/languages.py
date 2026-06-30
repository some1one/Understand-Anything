"""Shared language/category detection, ignore filtering, and file enumeration.

This module is the Python port of the detection tables and ignore logic that
previously lived in ``skills/understand/scan-project.mjs`` and the
``@understand-anything/core`` ``ignore-filter.ts`` / ``ignore-generator.ts``
modules. It is the single source of truth reused by :mod:`arch_analysis.scan_project`,
:mod:`arch_analysis.compute_batches`, and the structural extractors.

Where the core TypeScript configs and ``project-scanner.md`` diverge (rare),
``project-scanner.md`` wins because it is the user-facing contract.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pathspec

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

# Extension -> language id. Lowercase keys; lookup is ``ext.lower()``.
# ``.cfg``/``.ini``/``.env`` -> ``config`` is a *language id* here, not a
# category; category routing for these is handled by CATEGORY_BY_EXT.
LANGUAGE_BY_EXT: dict[str, str] = {
    # TypeScript / JavaScript
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    # Python
    ".py": "python",
    ".pyi": "python",
    # Go / Rust / Java / Kotlin / C# / Swift / Lua
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".swift": "swift",
    ".lua": "lua",
    # Ruby / PHP
    ".rb": "ruby",
    ".rake": "ruby",
    ".php": "php",
    # C / C++
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    # Vue / Svelte (no tree-sitter extractor; import map returns [])
    ".vue": "vue",
    ".svelte": "svelte",
    # Shell
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    # Markup / docs
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "markdown",
    # Config / data
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".jsonc": "jsonc",
    ".toml": "toml",
    ".xml": "xml",
    ".xsl": "xml",
    ".xsd": "xml",
    ".plist": "xml",
    ".cfg": "config",
    ".ini": "config",
    ".env": "config",
    # Data / schema
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".prisma": "prisma",
    ".csv": "csv",
    ".tsv": "csv",
    # Infra
    ".tf": "terraform",
    ".tfvars": "terraform",
    # JVM build files
    ".gradle": "gradle",
    # .NET project files
    ".csproj": "csproj",
    ".sln": "sln",
    ".properties": "properties",
    ".mod": "mod",
    ".sum": "sum",
}

# Filename (no extension) -> language id. Compared case-sensitively against
# the basename. Dockerfile.* variants are handled by a prefix check.
LANGUAGE_BY_FILENAME: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "makefile",
    "GNUmakefile": "makefile",
    "makefile": "makefile",
    "Jenkinsfile": "jenkinsfile",
    "Procfile": "procfile",
    "Vagrantfile": "vagrantfile",
}

UNSUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".ps1", ".psm1", ".psd1", ".bat", ".cmd"}
)


def _ext(path: str) -> str:
    """Return the lowercase extension including the leading dot, or ''.

    Mirrors Node's ``path.extname``: for a basename like ``.env`` (a leading
    dotfile with no other dot) it returns ''. For ``archive.tar.gz`` it returns
    ``.gz``.
    """
    base = path.rsplit("/", 1)[-1]
    # A leading dot with no further dot is a dotfile, not an extension.
    dot = base.rfind(".")
    if dot <= 0:
        return ""
    return base[dot:].lower()


def _dotfile_key(base: str) -> str | None:
    """Extract the canonical dotfile "extension" from a basename, or None.

    ``.env`` -> ``.env``; ``.env.local`` -> ``.env``; ``.bashrc`` -> ``.bashrc``;
    ``package.json`` -> None (not a dotfile).
    """
    if not base.startswith("."):
        return None
    # Leading ``.`` followed by one or more alnum chars.
    i = 1
    while i < len(base) and (base[i].isalnum()):
        i += 1
    if i == 1:
        return None
    return base[:i].lower()


def detect_language(file_path: str) -> str:
    """Detect a file's language id. Never returns None.

    Falls back to the lowercased extension (without dot), then ``unknown``.
    """
    base = file_path.rsplit("/", 1)[-1]
    ext = _ext(file_path)

    if base == "Dockerfile" or base.startswith("Dockerfile."):
        return "dockerfile"

    dot_key = _dotfile_key(base)
    if dot_key and dot_key in LANGUAGE_BY_EXT:
        return LANGUAGE_BY_EXT[dot_key]

    if ext:
        by_ext = LANGUAGE_BY_EXT.get(ext)
        if by_ext:
            return by_ext
        return ext[1:]

    by_filename = LANGUAGE_BY_FILENAME.get(base)
    if by_filename:
        return by_filename

    return "unknown"


def is_unsupported_file(file_path: str) -> bool:
    return _ext(file_path) in UNSUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# Category detection (project-scanner.md Step 4)
# ---------------------------------------------------------------------------

CATEGORY_BY_EXT: dict[str, str] = {
    # docs
    ".md": "docs",
    ".mdx": "docs",
    ".rst": "docs",
    ".txt": "docs",
    ".text": "docs",
    # config
    ".yaml": "config",
    ".yml": "config",
    ".json": "config",
    ".jsonc": "config",
    ".toml": "config",
    ".xml": "config",
    ".xsl": "config",
    ".xsd": "config",
    ".plist": "config",
    ".cfg": "config",
    ".ini": "config",
    ".env": "config",
    ".properties": "config",
    ".csproj": "config",
    ".sln": "config",
    ".mod": "config",
    ".sum": "config",
    ".gradle": "config",
    # infra
    ".tf": "infra",
    ".tfvars": "infra",
    # data
    ".sql": "data",
    ".graphql": "data",
    ".gql": "data",
    ".proto": "data",
    ".prisma": "data",
    ".csv": "data",
    ".tsv": "data",
    # script
    ".sh": "script",
    ".bash": "script",
    ".zsh": "script",
    # markup
    ".html": "markup",
    ".htm": "markup",
    ".css": "markup",
    ".scss": "markup",
    ".sass": "markup",
    ".less": "markup",
}

INFRA_FILENAMES: frozenset[str] = frozenset(
    {
        "Dockerfile",
        ".dockerignore",
        "Makefile",
        "GNUmakefile",
        "makefile",
        "Jenkinsfile",
        "Procfile",
        "Vagrantfile",
        ".gitlab-ci.yml",
    }
)

import re as _re

_K8S_SEGMENT = _re.compile(r"(^|/)(k8s|kubernetes)/")
_K8S_SUFFIX = _re.compile(r"\.k8s\.(ya?ml)$", _re.IGNORECASE)


def detect_category(file_path: str) -> str:
    """Detect the project-scanner category for a file (priority-ordered)."""
    base = file_path.rsplit("/", 1)[-1]
    ext = _ext(file_path)
    posix = file_path.replace(os.sep, "/")

    # Rule 1: LICENSE exception.
    if base == "LICENSE":
        return "code"

    # Rule 2: infra by filename.
    if base in INFRA_FILENAMES:
        return "infra"
    if base == "Dockerfile" or base.startswith("Dockerfile."):
        return "infra"
    if base.startswith("docker-compose."):
        return "infra"
    if base in ("compose.yml", "compose.yaml"):
        return "infra"

    # Rule 3: infra by path.
    if posix.startswith(".github/workflows/"):
        return "infra"
    if posix.startswith(".circleci/"):
        return "infra"
    if _K8S_SEGMENT.search(posix):
        return "infra"
    if _K8S_SUFFIX.search(base):
        return "infra"

    # Rule 4: extension-based lookup.
    if ext:
        by_ext = CATEGORY_BY_EXT.get(ext)
        if by_ext:
            return by_ext

    # Rule 4.5: dotfile-style configs (.env, .env.local, .env.production).
    dot_key = _dotfile_key(base)
    if dot_key:
        by_dot = CATEGORY_BY_EXT.get(dot_key)
        if by_dot:
            return by_dot

    # Rule 5: fallback.
    return "code"


# ---------------------------------------------------------------------------
# Complexity estimation (project-scanner.md Step 7)
# ---------------------------------------------------------------------------


def estimate_complexity(total_files: int) -> str:
    """Map a total file count to a complexity tier (lower bound inclusive)."""
    if total_files <= 30:
        return "small"
    if total_files <= 150:
        return "moderate"
    if total_files <= 500:
        return "large"
    return "very-large"


# ---------------------------------------------------------------------------
# Ignore filtering — port of @understand-anything/core ignore-filter.ts
# ---------------------------------------------------------------------------

# Hardcoded default ignore patterns matching the project-scanner agent's
# exclusion rules, plus bin/obj for .NET projects.
DEFAULT_IGNORE_PATTERNS: list[str] = [
    # Dependency directories
    "node_modules/",
    ".git/",
    "vendor/",
    "venv/",
    ".venv/",
    "__pycache__/",
    # Build output
    "dist/",
    "build/",
    "out/",
    "coverage/",
    ".next/",
    ".cache/",
    ".turbo/",
    "target/",
    "obj/",
    # Lock files
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    # Binary/asset files
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.ico",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.eot",
    "*.mp3",
    "*.mp4",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    # Generated files
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.generated.*",
    # IDE/editor
    ".idea/",
    ".vscode/",
    # Misc
    "LICENSE",
    ".gitignore",
    ".editorconfig",
    ".prettierrc",
    ".eslintrc*",
    "*.log",
]


class IgnoreFilter:
    """Returns whether a project-relative path should be excluded.

    Uses ``pathspec`` gitwildmatch semantics, matching the gitignore-compatible
    ``ignore`` npm package used by core. Patterns are layered (later negations
    override earlier patterns):

    1. Hardcoded defaults
    2. ``.understand-anything/.understandignore`` (if present)
    3. ``.understandignore`` at the project root (if present)
    """

    def __init__(self, patterns: list[str]):
        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)

    def is_ignored(self, relative_path: str) -> bool:
        return self._spec.match_file(relative_path)


def _read_ignore_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def create_ignore_filter(project_root: str | Path) -> IgnoreFilter:
    """Build an IgnoreFilter merging defaults with user ``.understandignore``."""
    root = Path(project_root)
    patterns = list(DEFAULT_IGNORE_PATTERNS)

    project_ignore = root / ".understand-anything" / ".understandignore"
    if project_ignore.exists():
        patterns.extend(_read_ignore_lines(project_ignore))

    root_ignore = root / ".understandignore"
    if root_ignore.exists():
        patterns.extend(_read_ignore_lines(root_ignore))

    return IgnoreFilter(patterns)


def build_defaults_only_filter() -> IgnoreFilter:
    """An IgnoreFilter with only the hardcoded defaults (no user patterns)."""
    return IgnoreFilter(list(DEFAULT_IGNORE_PATTERNS))


def has_user_ignore_file(project_root: str | Path) -> bool:
    root = Path(project_root)
    return (root / ".understandignore").exists() or (
        root / ".understand-anything" / ".understandignore"
    ).exists()


# ---------------------------------------------------------------------------
# File enumeration
# ---------------------------------------------------------------------------

_HARD_SKIP_DIRS: frozenset[str] = frozenset(
    {"node_modules", ".git", ".svn", ".hg", "__pycache__"}
)


def enumerate_via_git(project_root: str | Path) -> list[str] | None:
    """Enumerate files via ``git ls-files``. None if not a git repo.

    Uses ``-z`` (NUL-terminated) so non-ASCII path bytes round-trip cleanly.
    Returns project-relative POSIX paths (git emits forward slashes on all OSes).
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "-co", "--exclude-standard"],
            cwd=str(project_root),
            capture_output=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0 or not result.stdout:
        # returncode 0 with empty stdout (empty repo) is a valid empty listing.
        if result.returncode == 0:
            return []
        return None
    raw = result.stdout.decode("utf-8", errors="surrogateescape")
    return [p for p in raw.split("\0") if p]


def enumerate_via_walk(project_root: str | Path) -> list[str]:
    """Recursive directory walker fallback (no .gitignore awareness)."""
    root = Path(project_root)
    out: list[str] = []

    def walk(abs_dir: Path) -> None:
        try:
            entries = sorted(os.scandir(abs_dir), key=lambda e: e.name)
        except OSError:
            return
        for ent in entries:
            if ent.is_dir(follow_symlinks=False):
                if ent.name in _HARD_SKIP_DIRS:
                    continue
                walk(Path(ent.path))
            elif ent.is_file(follow_symlinks=False):
                rel = os.path.relpath(ent.path, root).replace(os.sep, "/")
                if rel and rel != ".":
                    out.append(rel)
            # Symlinks intentionally ignored.

    walk(root)
    return out


def enumerate_files(project_root: str | Path) -> list[str]:
    """Enumerate candidate files: git ls-files first, recursive walk fallback."""
    from_git = enumerate_via_git(project_root)
    if from_git is not None:
        return from_git
    return enumerate_via_walk(project_root)
