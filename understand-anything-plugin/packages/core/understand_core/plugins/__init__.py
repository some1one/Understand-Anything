"""Analyzer functionality: tree-sitter structural analysis, extractors, parsers.

Exposes the analyzers directly — there is no plugin registry / config-driven
loading layer. Call :class:`TreeSitterPlugin` (code) or a parser (non-code)
directly, or iterate :data:`~understand_core.plugins.extractors.builtin_extractors`.
"""

from __future__ import annotations

from understand_core.plugins.tree_sitter_plugin import TreeSitterPlugin

__all__ = [
    "TreeSitterPlugin",
]
