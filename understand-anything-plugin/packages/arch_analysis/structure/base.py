"""Shared AST helpers and the StructuralAnalysis container.

Port of ``@understand-anything/core``'s ``base-extractor.ts`` plus the shape
of the ``StructuralAnalysis`` interface from ``core/src/types.ts``.

Tree-sitter nodes here are :class:`tree_sitter.Node` objects produced by
:func:`arch_analysis.treesitter.parse`. ``node.text`` is ``bytes`` (decoded via
:func:`txt`); ``node.start_point.row`` / ``end_point.row`` are 0-based (add 1
for human line numbers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tree_sitter import Node


# ---------------------------------------------------------------------------
# StructuralAnalysis container (mirrors core/src/types.ts)
# ---------------------------------------------------------------------------


@dataclass
class StructuralAnalysis:
    """Common structural-analysis shape returned by every extractor/parser.

    Code arrays (functions/classes/imports/exports) are always present (may be
    empty). Non-code arrays default to ``None`` so ``build_result`` can apply
    the same "present-but-maybe-empty vs. absent" semantics as the JS
    ``buildResult`` (which checks ``analysis.x`` for truthiness/length).
    """

    functions: list[dict] = field(default_factory=list)
    classes: list[dict] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    exports: list[dict] = field(default_factory=list)
    sections: list[dict] | None = None
    definitions: list[dict] | None = None
    services: list[dict] | None = None
    endpoints: list[dict] | None = None
    steps: list[dict] | None = None
    resources: list[dict] | None = None


def make_function(name: str, start_line: int, end_line: int, params: list[str],
                  return_type: str | None = None) -> dict:
    fn: dict = {"name": name, "lineRange": [start_line, end_line], "params": params}
    if return_type is not None:
        fn["returnType"] = return_type
    return fn


def make_class(name: str, start_line: int, end_line: int,
               methods: list[str], properties: list[str]) -> dict:
    return {
        "name": name,
        "lineRange": [start_line, end_line],
        "methods": methods,
        "properties": properties,
    }


def make_import(source: str, specifiers: list[str], line_number: int) -> dict:
    return {"source": source, "specifiers": specifiers, "lineNumber": line_number}


def make_export(name: str, line_number: int, is_default: bool | None = None) -> dict:
    exp: dict = {"name": name, "lineNumber": line_number}
    if is_default is not None:
        exp["isDefault"] = is_default
    return exp


# ---------------------------------------------------------------------------
# AST helpers (port of base-extractor.ts)
# ---------------------------------------------------------------------------


def txt(node: Node | None) -> str:
    """Decode a node's source text (``node.text`` is bytes)."""
    if node is None:
        return ""
    raw = node.text
    if raw is None:
        return ""
    return raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)


def row(node: Node) -> int:
    """1-based start line."""
    return node.start_point[0] + 1


def end_row(node: Node) -> int:
    """1-based end line."""
    return node.end_point[0] + 1


def traverse(node: Node, visitor: Callable[[Node], None]) -> None:
    """Pre-order traversal calling ``visitor`` for each node (incl. unnamed)."""
    visitor(node)
    for child in node.children:
        if child is not None:
            traverse(child, visitor)


def get_string_value(node: Node) -> str:
    """Unquoted value of a string-like node (port of getStringValue)."""
    for child in node.children:
        if child is not None and child.type == "string_fragment":
            return txt(child)
    s = txt(node)
    if len(s) >= 2 and s[0] in "'\"`" and s[-1] in "'\"`":
        # Strip one leading and one trailing quote char (matches the JS regex
        # ``/^['"`]|['"`]$/g`` which removes at most one on each end).
        s = s[1:]
        if s and s[-1] in "'\"`":
            s = s[:-1]
        return s
    # No surrounding quotes: still strip a single leading/trailing quote if any
    if s and s[0] in "'\"`":
        s = s[1:]
    if s and s[-1] in "'\"`":
        s = s[:-1]
    return s


def find_child(node: Node, type_: str) -> Node | None:
    for child in node.children:
        if child is not None and child.type == type_:
            return child
    return None


def find_children(node: Node, type_: str) -> list[Node]:
    return [c for c in node.children if c is not None and c.type == type_]


def has_child_of_type(node: Node, type_: str) -> bool:
    return find_child(node, type_) is not None


def child_field(node: Node, field_name: str) -> Node | None:
    return node.child_by_field_name(field_name)


def find_descendant_child(node: Node, predicate: Callable[[Node], bool]) -> Node | None:
    """First direct child matching ``predicate`` (port of ``children.find``)."""
    for child in node.children:
        if child is not None and predicate(child):
            return child
    return None
