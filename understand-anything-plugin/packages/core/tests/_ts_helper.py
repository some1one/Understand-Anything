"""Shared pytest helpers for extractor tests.

Provides a single ``parse_source`` that copes with the locally-installed
``tree_sitter`` binding (method-based node API, ``parse`` takes ``str``) and
returns a :class:`NodeAdapter`-wrapped root node, so the ported extractors see
the property-based API they were written against.
"""

from __future__ import annotations

from typing import Any

try:
    from tree_sitter_language_pack import get_parser as _get_parser
except Exception:  # pragma: no cover
    _get_parser = None  # type: ignore[assignment]

from understand_core.plugins.extractors.base_extractor import wrap_root


def get_parser(lang: str) -> Any:
    if _get_parser is None:  # pragma: no cover
        return None
    try:
        return _get_parser(lang)
    except Exception:  # pragma: no cover
        return None


def _root_node(tree: Any) -> Any:
    rn = tree.root_node
    return rn() if callable(rn) else rn


def parse_source(parser: Any, code: str):
    """Parse ``code`` with ``parser`` and return a wrapped root node."""
    src = code.encode("utf-8")
    try:
        tree = parser.parse(code)  # this binding wants str
    except TypeError:
        tree = parser.parse(src)  # reference binding wants bytes
    return wrap_root(_root_node(tree), src)
