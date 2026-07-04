"""AST traversal helpers + a node-compatibility adapter for extractors.

Port of ``plugins/extractors/base-extractor.ts``. The TS extractors were written
against ``web-tree-sitter``'s property-based ``Node`` API (``node.type``,
``node.children``, ``node.text`` as a string, ``node.startPosition.row`` …). The
Python ``tree_sitter`` binding available here exposes a *method*-based API with
different names (``node.kind()``, ``node.child(i)``, ``node.start_position()`` and
no ``.text`` at all — text must be sliced from the source bytes).

To keep all 11 ported extractors written against the familiar property API, raw
nodes are wrapped in :class:`NodeAdapter`, which re-exposes the surface the
extractors expect: ``.type``, ``.children``, ``.named_children``, ``.child_count``,
``.named_child_count``, ``.text`` (bytes), ``.start_point``, ``.end_point``,
``.child_by_field_name``, ``.is_named``, ``.parent`` and ``.id``.
"""

from __future__ import annotations

import re
from typing import Any, Callable

_QUOTE_RE = re.compile(r"^['\"`]|['\"`]$")


def _call(value: Any) -> Any:
    """Return ``value()`` if it is callable (method-based binding), else ``value``.

    The Python ``tree_sitter`` build exposes node members as methods, but the
    reference binding exposes them as properties. This tolerates both.
    """
    return value() if callable(value) else value


class NodeAdapter:
    """Wrap a raw tree-sitter node, exposing the property-based extractor API."""

    __slots__ = ("_node", "_source")

    def __init__(self, node: Any, source: bytes) -> None:
        self._node = node
        self._source = source

    # -- core ---------------------------------------------------------------

    @property
    def raw(self) -> Any:
        return self._node

    @property
    def type(self) -> str:
        node = self._node
        # Prefer ``type``; fall back to the method-based ``kind``.
        t = getattr(node, "type", None)
        if t is not None:
            return _call(t)
        return _call(node.kind)

    @property
    def text(self) -> bytes:
        """Source text as bytes (the TS ``.text`` string is decoded by callers)."""
        existing = getattr(self._node, "text", None)
        if existing is not None and not callable(existing):
            return existing if isinstance(existing, bytes) else str(existing).encode("utf-8")
        start = _call(self._node.start_byte)
        end = _call(self._node.end_byte)
        return self._source[start:end]

    @property
    def id(self) -> int:
        ident = getattr(self._node, "id", None)
        if ident is not None:
            return _call(ident)
        # Byte range uniquely identifies a node within a tree.
        return hash((_call(self._node.start_byte), _call(self._node.end_byte), self.type))

    @property
    def is_named(self) -> bool:
        return bool(_call(self._node.is_named))

    @property
    def start_byte(self) -> int:
        return _call(self._node.start_byte)

    @property
    def end_byte(self) -> int:
        return _call(self._node.end_byte)

    # -- positions ----------------------------------------------------------

    def _point(self, attr_property: str, attr_method: str) -> tuple[int, int]:
        node = self._node
        p = getattr(node, attr_property, None)
        if p is None:
            p = _call(getattr(node, attr_method))
        else:
            p = _call(p)
        row = getattr(p, "row", None)
        if row is not None:
            return (row, getattr(p, "column", 0))
        # Fall back to tuple-like Point.
        seq = tuple(p)
        return (seq[0], seq[1])

    @property
    def start_point(self) -> tuple[int, int]:
        return self._point("start_point", "start_position")

    @property
    def end_point(self) -> tuple[int, int]:
        return self._point("end_point", "end_position")

    # -- children -----------------------------------------------------------

    @property
    def child_count(self) -> int:
        return _call(self._node.child_count)

    @property
    def named_child_count(self) -> int:
        return _call(self._node.named_child_count)

    def _wrap(self, raw: Any) -> "NodeAdapter | None":
        return NodeAdapter(raw, self._source) if raw is not None else None

    @property
    def children(self) -> list["NodeAdapter"]:
        node = self._node
        raw_children = getattr(node, "children", None)
        if raw_children is not None and not callable(raw_children):
            return [self._wrap(c) for c in raw_children if c is not None]
        count = _call(node.child_count)
        result: list[NodeAdapter] = []
        for i in range(count):
            c = node.child(i)
            if c is not None:
                result.append(NodeAdapter(c, self._source))
        return result

    @property
    def named_children(self) -> list["NodeAdapter"]:
        node = self._node
        raw_named = getattr(node, "named_children", None)
        if raw_named is not None and not callable(raw_named):
            return [self._wrap(c) for c in raw_named if c is not None]
        count = _call(node.named_child_count)
        result: list[NodeAdapter] = []
        for i in range(count):
            c = node.named_child(i)
            if c is not None:
                result.append(NodeAdapter(c, self._source))
        return result

    def child_by_field_name(self, name: str) -> "NodeAdapter | None":
        raw = self._node.child_by_field_name(name)
        return self._wrap(raw)

    @property
    def parent(self) -> "NodeAdapter | None":
        raw = _call(getattr(self._node, "parent"))
        return self._wrap(raw)


def wrap_root(raw_node: Any, source: str | bytes) -> NodeAdapter:
    """Wrap a parsed tree's root node so extractors see the property API."""
    src = source.encode("utf-8") if isinstance(source, str) else source
    return NodeAdapter(raw_node, src)


# ---------------------------------------------------------------------------
# Traversal helpers (operate on NodeAdapter or any property-API node)
# ---------------------------------------------------------------------------


def node_text(node: Any) -> str:
    """Decode a node's source text to ``str``."""
    text = getattr(node, "text", b"")
    if callable(text):  # method-based raw node passed directly
        text = text()
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text)


def traverse(node: Any, visitor: Callable[[Any], None]) -> None:
    """Recursively visit ``node`` and all of its descendants."""
    visitor(node)
    for child in node.children:
        if child is not None:
            traverse(child, visitor)


def get_string_value(node: Any) -> str:
    """Extract the unquoted value from a string-like node."""
    for child in node.children:
        if child is not None and child.type == "string_fragment":
            return node_text(child)
    return _QUOTE_RE.sub("", node_text(node))


def find_child(node: Any, type_: str) -> Any | None:
    """First direct child of the given type, or ``None``."""
    for child in node.children:
        if child is not None and child.type == type_:
            return child
    return None


def find_children(node: Any, type_: str) -> list[Any]:
    """All direct children of the given type."""
    return [c for c in node.children if c is not None and c.type == type_]


def has_child_of_type(node: Any, type_: str) -> bool:
    """Whether ``node`` has a direct child of the given type."""
    return any(c is not None and c.type == type_ for c in node.children)
