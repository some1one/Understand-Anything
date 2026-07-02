"""Analyzer cluster — LLM prompt builders/parsers, layer detection, language
lessons, graph construction, and batch-output normalization.

Public API mirrors the TS ``packages/core/src/analyzer/`` exports.
"""

from __future__ import annotations

from .graph_builder import GraphBuilder
from .language_lesson import (
    LanguageLessonConcept,
    LanguageLessonResult,
    build_language_lesson_prompt,
    detect_language_concepts,
    get_language_display_name,
    parse_language_lesson_response,
)
from .layer_detector import (
    LLMLayerResponse,
    apply_llm_layers,
    build_layer_detection_prompt,
    detect_layers,
    parse_layer_detection_response,
)
from .llm_analyzer import (
    LLMFileAnalysis,
    LLMLayer,
    LLMProjectSummary,
    build_file_analysis_prompt,
    build_project_summary_prompt,
    parse_file_analysis_response,
    parse_project_summary_response,
)
from .normalize_graph import (
    DroppedEdge,
    NormalizationStats,
    NormalizeBatchResult,
    normalize_batch_output,
    normalize_complexity,
    normalize_node_id,
)

__all__ = [
    "LLMFileAnalysis",
    "LLMLayer",
    "LLMProjectSummary",
    "build_file_analysis_prompt",
    "build_project_summary_prompt",
    "parse_file_analysis_response",
    "parse_project_summary_response",
    "LLMLayerResponse",
    "apply_llm_layers",
    "build_layer_detection_prompt",
    "detect_layers",
    "parse_layer_detection_response",
    "LanguageLessonConcept",
    "LanguageLessonResult",
    "build_language_lesson_prompt",
    "detect_language_concepts",
    "get_language_display_name",
    "parse_language_lesson_response",
    "GraphBuilder",
    "DroppedEdge",
    "NormalizationStats",
    "NormalizeBatchResult",
    "normalize_batch_output",
    "normalize_complexity",
    "normalize_node_id",
]
