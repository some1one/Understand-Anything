"""Shared tree-sitter parser registry.

Maps Understand-Anything language ids (as produced by
:func:`arch_analysis.languages.detect_language`) to ``tree_sitter`` parsers
backed by ``tree_sitter_language_pack``. This replaces the
``web-tree-sitter`` WASM loading that the JS pipeline performed via
``@understand-anything/core``'s ``TreeSitterPlugin``.

Languages without a tree-sitter grammar resolve to ``None`` so callers can
degrade gracefully (the same contract as the JS plugin).
"""

from __future__ import annotations

from functools import lru_cache

from tree_sitter import Node, Parser

# Our language id -> tree_sitter_language_pack grammar name.
# ``tsx`` is a distinct grammar; ``typescript`` files use the ``typescript``
# grammar and ``.tsx`` files use ``tsx`` (mirrors core's special-casing).
_LANG_TO_GRAMMAR: dict[str, str] = {
    "typescript": "typescript",
    "tsx": "tsx",
    "javascript": "javascript",
    "python": "python",
    "go": "go",
    "rust": "rust",
    "java": "java",
    "kotlin": "kotlin",
    "csharp": "csharp",
    "php": "php",
    "ruby": "ruby",
    "c": "c",
    "cpp": "cpp",
}

#: Languages with structural/import extraction support.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(_LANG_TO_GRAMMAR)


@lru_cache(maxsize=None)
def get_parser(language_id: str) -> Parser | None:
    """Return a cached tree-sitter Parser for ``language_id``, or None.

    None is returned for unknown languages or when the grammar fails to load,
    so callers can skip structural analysis gracefully.
    """
    grammar = _LANG_TO_GRAMMAR.get(language_id)
    if grammar is None:
        return None
    try:
        # Build the Parser from the pack's ``Language`` rather than its
        # ``get_parser`` helper: the latter returns a parser bound to the
        # pack's vendored tree-sitter Rust core, whose ``parse`` is ABI-
        # incompatible with the installed ``tree_sitter`` wheel (it rejects
        # ``bytes`` with "'bytes' object is not an instance of 'str'").
        # ``get_language`` yields a plain ``tree_sitter.Language`` that the
        # installed ``Parser`` accepts.
        from tree_sitter_language_pack import get_language as _pack_get_language

        return Parser(_pack_get_language(grammar))  # type: ignore[arg-type]
    except Exception:
        return None


def parse(language_id: str, source: str | bytes) -> Node | None:
    """Parse ``source`` for ``language_id`` and return the root node, or None."""
    parser = get_parser(language_id)
    if parser is None:
        return None
    data = source.encode("utf-8") if isinstance(source, str) else source
    tree = parser.parse(data)
    return tree.root_node if tree is not None else None


def node_text(node: Node, source_bytes: bytes) -> str:
    """Return the UTF-8 text spanned by ``node``."""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")
