"""Architecture structural-analysis package.

Implements Phase 1 of the ``architecture-analyzer`` agent: the deterministic
graph- and path-based analytics that inform semantic layer assignment.

The analysis entry point lives in :mod:`arch_analysis.analyze`
(``from arch_analysis.analyze import analyze`` / ``python -m arch_analysis.analyze``).
"""

from __future__ import annotations

from .models import AnalysisInput, AnalysisResult, Edge, FileNode

__all__ = ["AnalysisInput", "AnalysisResult", "Edge", "FileNode"]
