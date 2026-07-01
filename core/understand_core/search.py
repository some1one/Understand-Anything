"""Fuzzy search over graph nodes.

Port of ``search.ts`` (which used fuse.js). Here we use ``rapidfuzz`` to score
weighted fuzzy matches across a node's ``name``, ``tags``, ``summary`` and
``languageNotes`` fields. Scores follow the fuse.js convention: ``0`` is a
perfect match and ``1`` is the worst.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from understand_core.types import GraphNode

# Field weights mirror the fuse.js config in search.ts.
_FIELD_WEIGHTS: list[tuple[str, float]] = [
    ("name", 0.4),
    ("tags", 0.3),
    ("summary", 0.2),
    ("languageNotes", 0.1),
]
_TOTAL_WEIGHT = sum(w for _, w in _FIELD_WEIGHTS)

# fuse.js threshold 0.4 → keep matches whose (1 - similarity) <= 0.4.
_THRESHOLD = 0.4

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class SearchResult:
    """A single search hit. ``score`` of 0 is a perfect match, 1 is worst."""

    node_id: str
    score: float


def _field_value(node: object, field: str) -> str:
    """Read a node field as text, joining list fields (tags) on spaces.

    Works with both pydantic models (snake_case attrs / camelCase aliases) and
    plain dicts.
    """
    if isinstance(node, dict):
        value = node.get(field)
    else:
        attr = {"languageNotes": "language_notes"}.get(field, field)
        value = getattr(node, attr, None)
        if value is None:
            value = getattr(node, field, None)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value)


def _node_id(node: object) -> str:
    if isinstance(node, dict):
        return str(node.get("id", ""))
    return str(getattr(node, "id", ""))


def _node_type(node: object) -> str:
    if isinstance(node, dict):
        return str(node.get("type", ""))
    return str(getattr(node, "type", ""))


def _aggregate_similarity(node: object, tokens: list[str]) -> float:
    """Best-field similarity in [0, 1], lightly biased by field weight.

    Mirrors fuse.js semantics: a strong match in any single key yields a high
    similarity (near 1) regardless of the other fields. The field's weight only
    breaks ties between equally strong matches (higher-weighted fields rank
    first), so e.g. an exact name match beats an equally fuzzy tag match.
    Query tokens are OR-combined: a field's score is its best single-token match.
    """
    best = 0.0
    for field, weight in _FIELD_WEIGHTS:
        text = _field_value(node, field)
        if not text:
            continue
        text_l = text.lower()
        field_sim = 0.0
        for token in tokens:
            tl = token.lower()
            s = max(fuzz.partial_ratio(tl, text_l), fuzz.token_set_ratio(tl, text_l))
            if s > field_sim:
                field_sim = s
        # Tiny weight bonus (<= 0.01) only nudges ordering; never lifts a weak
        # match above the threshold on its own.
        score = (field_sim / 100.0) + (weight / _TOTAL_WEIGHT) * 0.01
        if score > best:
            best = score
    return min(best, 1.0)


class SearchEngine:
    """Weighted fuzzy search engine over a list of graph nodes."""

    def __init__(self, nodes: Sequence[GraphNode]) -> None:
        self._nodes: list[GraphNode] = list(nodes)

    def search(
        self,
        query: str,
        types: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[SearchResult]:
        trimmed = query.strip()
        if not trimmed:
            return []

        tokens = [t for t in _WHITESPACE.split(trimmed) if t]
        allowed = set(types) if types else None

        scored: list[SearchResult] = []
        for node in self._nodes:
            if allowed is not None and _node_type(node) not in allowed:
                continue
            sim = _aggregate_similarity(node, tokens)
            score = 1.0 - sim
            if score <= _THRESHOLD:
                scored.append(SearchResult(node_id=_node_id(node), score=score))

        scored.sort(key=lambda r: r.score)
        return scored[:limit]

    def update_nodes(self, nodes: Sequence[GraphNode]) -> None:
        self._nodes = list(nodes)
