"""Shared StructuralAnalysis result helpers for non-code parsers.

The graph data types are owned by ``understand_core.types`` (a sibling cluster).
We import ``StructuralAnalysis`` from there when available; otherwise we fall
back to a lightweight attribute-access container so the parsers (and their
tests) remain usable independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:  # Prefer the canonical type when the types cluster is present.
    from understand_core.types import StructuralAnalysis as _StructuralAnalysis  # noqa: F401

    _HAVE_CANONICAL = True
except Exception:  # pragma: no cover - types cluster not present yet
    _HAVE_CANONICAL = False


@dataclass
class StructuralAnalysisResult:
    """Attribute-access container mirroring the ``StructuralAnalysis`` shape.

    Optional non-code fields default to ``None`` so ``result.sections`` etc.
    behave like the TS ``sections?`` optional properties.
    """

    functions: list[dict[str, Any]] = field(default_factory=list)
    classes: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    exports: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] | None = None
    definitions: list[dict[str, Any]] | None = None
    services: list[dict[str, Any]] | None = None
    endpoints: list[dict[str, Any]] | None = None
    steps: list[dict[str, Any]] | None = None
    resources: list[dict[str, Any]] | None = None


def make_analysis(**kwargs: Any) -> StructuralAnalysisResult:
    """Build a structural-analysis result; ``functions``/``classes``/``imports``/
    ``exports`` default to empty lists."""
    return StructuralAnalysisResult(**kwargs)
