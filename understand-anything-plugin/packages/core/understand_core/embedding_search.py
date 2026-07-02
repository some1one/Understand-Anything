"""Semantic (embedding) search over graph nodes.

Port of ``embedding-search.ts``. Cosine similarity is computed with ``numpy``.
Scores follow the same convention as :mod:`understand_core.search`: ``0`` is a
perfect match (similarity 1) and larger scores are worse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence

import numpy as np

if TYPE_CHECKING:
    from understand_core.types import GraphNode

# Re-use the SearchResult shape from the lexical search module so callers can
# treat both engines uniformly.
from understand_core.search import SearchResult

__all__ = ["cosine_similarity", "SemanticSearchEngine", "SearchResult"]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two vectors; 0 if either has zero magnitude."""
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    mag_a = float(np.linalg.norm(va))
    mag_b = float(np.linalg.norm(vb))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (mag_a * mag_b))


def _node_id(node: object) -> str:
    if isinstance(node, dict):
        return str(node.get("id", ""))
    return str(getattr(node, "id", ""))


def _node_type(node: object) -> str:
    if isinstance(node, dict):
        return str(node.get("type", ""))
    return str(getattr(node, "type", ""))


class SemanticSearchEngine:
    """Vector-embedding search engine using cosine similarity.

    Stores pre-computed embeddings for graph nodes and ranks them against a
    query embedding.
    """

    def __init__(
        self,
        nodes: Sequence[GraphNode],
        embeddings: Mapping[str, Sequence[float]],
    ) -> None:
        self._nodes: list[GraphNode] = list(nodes)
        self._embeddings: dict[str, list[float]] = {
            k: list(v) for k, v in embeddings.items()
        }

    def has_embeddings(self) -> bool:
        return len(self._embeddings) > 0

    def add_embedding(self, node_id: str, embedding: Sequence[float]) -> None:
        self._embeddings[node_id] = list(embedding)

    def search(
        self,
        query_embedding: Sequence[float],
        limit: int = 10,
        threshold: float = 0.0,
        types: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        type_filter = set(types) if types else None

        scored: list[SearchResult] = []
        for node in self._nodes:
            if type_filter is not None and _node_type(node) not in type_filter:
                continue
            embedding = self._embeddings.get(_node_id(node))
            if embedding is None:
                continue
            similarity = cosine_similarity(query_embedding, embedding)
            if similarity >= threshold:
                scored.append(SearchResult(node_id=_node_id(node), score=1.0 - similarity))

        scored.sort(key=lambda r: r.score)
        return scored[:limit]

    def update_nodes(self, nodes: Sequence[GraphNode]) -> None:
        self._nodes = list(nodes)
