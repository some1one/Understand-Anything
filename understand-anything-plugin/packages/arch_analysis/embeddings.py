"""Embedding generation & persistence for the deterministic pipeline.

Produces a companion ``embeddings.json`` file next to ``knowledge-graph.json``
so the dashboard can lazy-load per-node vectors only when semantic search is
active. The graph JSON itself stays small — embeddings are never inlined on
nodes.

Serialized contract (``.understand-anything/embeddings.json``)::

    {
      "model": "<embedding-model-id>",
      "dim": 1536,
      "embeddings": { "<nodeId>": [/* dim floats */], "...": [] }
    }

The network call sits behind the :class:`EmbeddingClient` protocol so it can be
stubbed in tests. Generation is opt-in (it needs an API key); absence of the
file is a clean "semantic unavailable" signal for consumers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

__all__ = [
    "EmbeddingClient",
    "EmbeddingResult",
    "node_text",
    "build_embeddings",
    "save_embeddings",
    "load_embeddings",
    "generate_and_save",
    "embeddings_enabled",
    "default_client",
]

# Default embeddings location relative to a project root.
EMBEDDINGS_FILENAME = "embeddings.json"

# Environment configuration (opt-in; OpenAI-compatible endpoint).
ENV_API_KEY = "UNDERSTAND_EMBEDDINGS_API_KEY"
ENV_MODEL = "UNDERSTAND_EMBEDDINGS_MODEL"
ENV_BASE_URL = "UNDERSTAND_EMBEDDINGS_BASE_URL"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


@runtime_checkable
class EmbeddingClient(Protocol):
    """Anything that turns a batch of strings into a batch of vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(eq=True)
class EmbeddingResult:
    """In-memory form of ``embeddings.json``."""

    model: str
    dim: int
    embeddings: dict[str, list[float]]


def _field(node: object, key: str, default: Any) -> Any:
    if isinstance(node, dict):
        return node.get(key, default)
    return getattr(node, key, default)


def node_text(node: object) -> str:
    """Build the string to embed for a node: name + summary + tags."""
    name = str(_field(node, "name", "") or "")
    summary = str(_field(node, "summary", "") or "")
    tags = _field(node, "tags", []) or []
    tag_text = " ".join(str(t) for t in tags)
    parts = [p.strip() for p in (name, summary, tag_text)]
    return "\n".join(p for p in parts if p)


def build_embeddings(
    nodes: Sequence[object],
    client: EmbeddingClient,
    *,
    model: str = DEFAULT_MODEL,
    batch_size: int = 64,
) -> EmbeddingResult:
    """Embed every node with meaningful text, keyed by node id.

    Nodes without an id or without embeddable text are skipped.
    """
    embeddable: list[tuple[str, str]] = []
    for node in nodes:
        node_id = str(_field(node, "id", "") or "")
        text = node_text(node)
        if not node_id or not text.strip():
            continue
        embeddable.append((node_id, text))

    embeddings: dict[str, list[float]] = {}
    for start in range(0, len(embeddable), max(1, batch_size)):
        batch = embeddable[start : start + batch_size]
        vectors = client.embed([text for _, text in batch])
        for (node_id, _), vector in zip(batch, vectors):
            embeddings[node_id] = [float(x) for x in vector]

    dim = len(next(iter(embeddings.values()))) if embeddings else 0
    return EmbeddingResult(model=model, dim=dim, embeddings=embeddings)


def save_embeddings(path: str | os.PathLike[str], result: EmbeddingResult) -> None:
    """Write ``result`` to ``path`` using the JSON contract."""
    payload = {
        "model": result.model,
        "dim": result.dim,
        "embeddings": result.embeddings,
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_embeddings(path: str | os.PathLike[str]) -> EmbeddingResult | None:
    """Load an :class:`EmbeddingResult`, or ``None`` if the file is absent."""
    p = Path(path)
    if not p.is_file():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return EmbeddingResult(
        model=str(raw.get("model", "")),
        dim=int(raw.get("dim", 0)),
        embeddings={k: [float(x) for x in v] for k, v in raw.get("embeddings", {}).items()},
    )


def embeddings_enabled() -> bool:
    """True when an embedding API key is configured (generation is opt-in)."""
    return bool(os.environ.get(ENV_API_KEY, "").strip())


def default_client() -> EmbeddingClient:
    """Construct the OpenAI-compatible client from environment configuration.

    Raises ``RuntimeError`` when no API key is configured.
    """
    api_key = os.environ.get(ENV_API_KEY, "").strip()
    if not api_key:
        raise RuntimeError(f"{ENV_API_KEY} is not set")
    model = os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL
    base_url = os.environ.get(ENV_BASE_URL, "").strip() or DEFAULT_BASE_URL
    return _HttpEmbeddingClient(api_key=api_key, model=model, base_url=base_url)


class _HttpEmbeddingClient:
    """Minimal stdlib client for an OpenAI-compatible ``/embeddings`` endpoint."""

    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def embed(self, texts: list[str]) -> list[list[float]]:
        import urllib.request

        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:  # noqa: S310 (configured URL)
            payload = json.loads(response.read().decode("utf-8"))
        data = sorted(payload["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in data]


def generate_and_save(
    project_root: str | os.PathLike[str],
    nodes: Sequence[object],
    *,
    client: EmbeddingClient | None = None,
    model: str | None = None,
) -> Path:
    """Generate embeddings for ``nodes`` and write ``embeddings.json``.

    When ``client`` is omitted the environment-configured :func:`default_client`
    is used. Returns the path written.
    """
    if client is None:
        client = default_client()
    resolved_model = model or os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL
    result = build_embeddings(nodes, client, model=resolved_model)
    out_path = Path(project_root) / ".understand-anything" / EMBEDDINGS_FILENAME
    save_embeddings(out_path, result)
    return out_path
