"""Structural extraction submodule (Python port of @understand-anything/core).

Public entry points used by :mod:`understand_core.extract_structure`:
- :func:`analyze_file` — file path + content -> :class:`StructuralAnalysis` | None
- :func:`extract_call_graph` — file path + content -> call-graph edges | None
"""

from .base import StructuralAnalysis
from .registry import analyze_file, detect_registry_language, extract_call_graph

__all__ = [
    "StructuralAnalysis",
    "analyze_file",
    "extract_call_graph",
    "detect_registry_language",
]
