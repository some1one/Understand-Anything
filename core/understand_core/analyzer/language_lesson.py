"""Language-specific lesson generation — port of ``analyzer/language-lesson.ts``.

Detects programming concepts present in a graph node, builds an LLM prompt that
asks for a beginner-friendly language lesson, and parses the response. New port
(no ``arch_analysis`` equivalent).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from ..types import GraphEdge, GraphNode

if TYPE_CHECKING:  # pragma: no cover — languages cluster ported separately
    from ..languages.types import LanguageConfig


class LanguageLessonConcept(BaseModel):
    """A single detected/explained concept."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    explanation: str


class LanguageLessonResult(BaseModel):
    """Parsed result of a language-lesson LLM response."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    languageNotes: str = ""
    concepts: list[LanguageLessonConcept] = Field(default_factory=list)


# Base concept patterns that apply across all languages. These are merged with
# language-specific concepts from a LanguageConfig.
_BASE_CONCEPT_PATTERNS: dict[str, list[str]] = {
    "async/await": ["async", "await", "promise", "asynchronous"],
    "middleware pattern": ["middleware", "interceptor", "pipe"],
    "generics": ["generic", "type parameter", "template"],
    "decorators": ["decorator", "@", "annotation"],
    "dependency injection": ["inject", "provider", "container", "di"],
    "observer pattern": [
        "subscribe", "publish", "event", "observable", "listener",
    ],
    "singleton": ["singleton", "instance", "shared client"],
    "type guards": ["type guard", "is", "narrowing", "discriminated union"],
    "higher-order functions": ["callback", "factory", "higher-order", "closure"],
    "error handling": ["try/catch", "error boundary", "exception", "Result type"],
    "streams": ["stream", "pipe", "transform", "readable", "writable"],
    "concurrency": ["goroutine", "channel", "thread", "worker", "mutex"],
}


def _lang_concepts(lang_config: Any) -> list[str] | None:
    """Read a config's ``concepts`` regardless of attr or key access."""
    if lang_config is None:
        return None
    concepts = getattr(lang_config, "concepts", None)
    if concepts is None and isinstance(lang_config, dict):
        concepts = lang_config.get("concepts")
    return concepts


def _lang_display_name(lang_config: Any) -> str | None:
    """Read a config's display name (``displayName``/``display_name``)."""
    if lang_config is None:
        return None
    for attr in ("displayName", "display_name"):
        value = getattr(lang_config, attr, None)
        if value:
            return value
    if isinstance(lang_config, dict):
        return lang_config.get("displayName") or lang_config.get("display_name")
    return None


def _build_concept_patterns(
    lang_config: "LanguageConfig | None" = None,
) -> dict[str, list[str]]:
    """Merge base patterns with language-specific concepts from a config."""
    patterns = dict(_BASE_CONCEPT_PATTERNS)
    concepts = _lang_concepts(lang_config)
    if concepts:
        for concept in concepts:
            if concept not in patterns:
                patterns[concept] = [concept.lower()]
    return patterns


def detect_language_concepts(
    node: GraphNode,
    language: str,
    lang_config: "LanguageConfig | None" = None,
) -> list[str]:
    """Detect language concepts in a node from its tags, summary, and notes."""
    language_notes = getattr(node, "languageNotes", None) or ""
    text = " ".join(
        [
            *node.tags,
            node.summary.lower(),
            language_notes.lower(),
        ]
    )
    text_lower = text.lower()

    patterns = _build_concept_patterns(lang_config)
    detected: list[str] = []
    for concept, keywords in patterns.items():
        if any(keyword.lower() in text_lower for keyword in keywords):
            detected.append(concept)
    return detected


def get_language_display_name(
    language: str,
    lang_config: "LanguageConfig | None" = None,
) -> str:
    """Display name for a language — config wins, else capitalize ``language``."""
    display = _lang_display_name(lang_config)
    if display:
        return display
    if not language:
        return language
    return language[0].upper() + language[1:]


def build_language_lesson_prompt(
    node: GraphNode,
    edges: list[GraphEdge],
    language: str,
    lang_config: "LanguageConfig | None" = None,
) -> str:
    """Build a prompt asking an LLM for a language-specific lesson on a node."""
    capitalized_language = get_language_display_name(language, lang_config)
    concepts = detect_language_concepts(node, language, lang_config)

    relationship_lines: list[str] = []
    for edge in edges:
        arrow = "->" if edge.direction == "forward" else "<-"
        other = edge.target if edge.source == node.id else edge.source
        relationship_lines.append(f"  {arrow} {edge.type} {other}")
    relationships = "\n".join(relationship_lines)

    if concepts:
        concept_lines = "\n".join(f"  - {c}" for c in concepts)
        concept_section = f"\nDetected concepts to explain:\n{concept_lines}"
    else:
        concept_section = (
            f"\nNo specific concepts were pre-detected. Please identify any "
            f"{capitalized_language} patterns or idioms present."
        )

    tags = ", ".join(node.tags)
    file_path = node.filePath or "N/A"

    return f"""You are a programming teacher specializing in {capitalized_language}. Analyze the following code component and create a language-specific lesson.

Component: {node.name}
Type: {node.type}
File: {file_path}
Summary: {node.summary}
Tags: {tags}

Relationships:
{relationships}
{concept_section}

Return a JSON object with the following fields:
- "languageNotes": A concise explanation of the {capitalized_language}-specific patterns and idioms used in this component.
- "concepts": An array of objects, each with:
  - "name": The concept name (e.g., "async/await", "generics").
  - "explanation": A beginner-friendly explanation of this concept as it applies to this component.

Respond ONLY with the JSON object, no additional text."""


def _extract_json(response: str) -> str:
    """Extract a JSON block from an LLM response, handling markdown fences."""
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", response)
    if fence_match:
        return fence_match.group(1).strip()
    object_match = re.search(r"\{[\s\S]*\}", response)
    if object_match:
        return object_match.group(0).strip()
    return response.strip()


def parse_language_lesson_response(response: str) -> LanguageLessonResult:
    """Parse a language-lesson LLM response. Returns a safe default on failure."""
    try:
        parsed: Any = json.loads(_extract_json(response))
    except (ValueError, TypeError):
        return LanguageLessonResult(languageNotes="", concepts=[])
    if not isinstance(parsed, dict):
        return LanguageLessonResult(languageNotes="", concepts=[])

    raw_notes = parsed.get("languageNotes")
    language_notes = raw_notes if isinstance(raw_notes, str) else ""

    concepts: list[LanguageLessonConcept] = []
    raw_concepts = parsed.get("concepts")
    if isinstance(raw_concepts, list):
        for concept in raw_concepts:
            if (
                isinstance(concept, dict)
                and isinstance(concept.get("name"), str)
                and isinstance(concept.get("explanation"), str)
            ):
                concepts.append(
                    LanguageLessonConcept(
                        name=concept["name"],
                        explanation=concept["explanation"],
                    )
                )

    return LanguageLessonResult(languageNotes=language_notes, concepts=concepts)
