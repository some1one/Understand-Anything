"""Shared types for language extractors.

Port of ``plugins/extractors/types.ts``. ``TreeSitterNode`` aliases the Python
``tree_sitter.Node`` (the WASM ``web-tree-sitter.Node`` in the TS original).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from understand_core.types import CallGraphEntry, StructuralAnalysis

try:
    from tree_sitter import Node as TreeSitterNode
except Exception:  # pragma: no cover - tree_sitter optional at import time
    TreeSitterNode = object  # type: ignore[assignment,misc]


@runtime_checkable
class LanguageExtractor(Protocol):
    """Maps a tree-sitter AST to the common structural / call-graph types."""

    language_ids: list[str]

    def extract_structure(self, root_node: "TreeSitterNode") -> "StructuralAnalysis": ...

    def extract_call_graph(self, root_node: "TreeSitterNode") -> "list[CallGraphEntry]": ...
