"""Dispatch: file path -> language id -> extractor / parser.

Mirrors how ``@understand-anything/core``'s ``PluginRegistry.analyzeFile``
resolves a file: ``LanguageRegistry.getForFile`` maps the path to a
``LanguageConfig.id`` (filename match first, then extension), and the plugin
registered for that id handles it.

We reproduce just the extension/filename tables of the builtin
``LanguageConfig`` entries that have a registered extractor or parser, so the
right tree-sitter extractor / non-code parser is chosen for each file. This is
deliberately distinct from :func:`arch_analysis.languages.detect_language`,
because the registry uses its own config ids (e.g. ``docker-compose``,
``makefile``, ``json``) for parser routing.
"""

from __future__ import annotations

from tree_sitter import Node

from ..treesitter import parse
from .base import StructuralAnalysis
from .code_extractors import get_extractor
from .parsers import get_parser_for_language

# Filename (lowercased) -> registry language id. Filename match wins over
# extension (LanguageRegistry.getForFile checks byFilename first).
_FILENAME_TO_ID: dict[str, str] = {
    # env
    ".env": "env",
    ".env.local": "env",
    ".env.development": "env",
    ".env.production": "env",
    ".env.test": "env",
    ".env.example": "env",
    # dockerfile
    "dockerfile": "dockerfile",
    "dockerfile.dev": "dockerfile",
    "dockerfile.prod": "dockerfile",
    "dockerfile.test": "dockerfile",
    # docker-compose
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    "compose.yml": "docker-compose",
    "compose.yaml": "docker-compose",
    # openapi
    "openapi.yaml": "openapi",
    "openapi.json": "openapi",
    "swagger.yaml": "openapi",
    "swagger.json": "openapi",
    # makefile
    "makefile": "makefile",
    "gnumakefile": "makefile",
    # jenkinsfile
    "jenkinsfile": "jenkinsfile",
}

# Extension (lowercased, with dot) -> registry language id. Only extensions
# whose id has a registered extractor or parser are listed.
_EXT_TO_ID: dict[str, str] = {
    # code (tree-sitter)
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".py": "python",
    ".pyi": "python",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
    ".rake": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    # non-code parsers
    ".md": "markdown",
    ".mdx": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".jsonc": "json",
    ".toml": "toml",
    ".env": "env",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".mk": "makefile",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
}

#: Tree-sitter grammar language ids (used to route to the parser + extractor).
_TREE_SITTER_IDS = frozenset(
    {
        "typescript",
        "tsx",
        "javascript",
        "python",
        "go",
        "rust",
        "java",
        "kotlin",
        "csharp",
        "php",
        "ruby",
        "c",
        "cpp",
    }
)


def detect_registry_language(file_path: str) -> str | None:
    """Map a file path to a registry language id (or None).

    Filename match (case-insensitive) takes priority over extension, matching
    ``LanguageRegistry.getForFile``.
    """
    basename = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    by_filename = _FILENAME_TO_ID.get(basename.lower())
    if by_filename is not None:
        return by_filename
    last_dot = file_path.rfind(".")
    if last_dot == -1:
        return None
    ext = file_path[last_dot:].lower()
    return _EXT_TO_ID.get(ext)


def analyze_file(file_path: str, content: str) -> StructuralAnalysis | None:
    """Structural analysis for a file, or None when no plugin matches.

    Code files go through the tree-sitter extractor; non-code files through
    the matching parser. Returns None when no plugin is registered for the
    file's language id (matches ``PluginRegistry.analyzeFile`` returning null).
    """
    lang_id = detect_registry_language(file_path)
    if lang_id is None:
        return None

    if lang_id in _TREE_SITTER_IDS:
        # tsx uses the tsx grammar; extractor is the TypeScript one.
        grammar_id = lang_id
        root = parse(grammar_id, content)
        if root is None:
            return StructuralAnalysis()
        extractor = get_extractor(lang_id)
        if extractor is None:
            return StructuralAnalysis()
        return extractor.extract_structure(root)

    parser = get_parser_for_language(lang_id)
    if parser is None:
        return None
    return parser.analyze_file(content)


def extract_call_graph(file_path: str, content: str) -> list[dict] | None:
    """Call-graph edges for a file, or None when no code extractor matches."""
    lang_id = detect_registry_language(file_path)
    if lang_id is None or lang_id not in _TREE_SITTER_IDS:
        return None
    root = parse(lang_id, content)
    if root is None:
        return []
    extractor = get_extractor(lang_id)
    if extractor is None:
        return []
    return extractor.extract_call_graph(root)
