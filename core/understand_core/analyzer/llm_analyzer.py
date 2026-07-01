"""LLM prompt builders and response parsers — port of ``analyzer/llm-analyzer.ts``.

Builds the prompts sent to an LLM for per-file and project-level analysis and
parses the JSON responses back into typed pydantic models. Parsing is lenient:
markdown code fences are stripped, missing fields default safely, and a failed
parse returns ``None`` (rather than raising).
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# JSON wire keys stay camelCase to match the TS source and the rest of the port.

VALID_COMPLEXITIES: frozenset[str] = frozenset({"simple", "moderate", "complex"})


class LLMLayer(BaseModel):
    """A logical layer entry inside an :class:`LLMProjectSummary`."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    description: str = ""
    filePatterns: list[str] = Field(default_factory=list)


class LLMFileAnalysis(BaseModel):
    """Parsed result of a single-file LLM analysis."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    fileSummary: str = ""
    tags: list[str] = Field(default_factory=list)
    complexity: str = "moderate"
    functionSummaries: dict[str, str] = Field(default_factory=dict)
    classSummaries: dict[str, str] = Field(default_factory=dict)
    languageNotes: str | None = None


class LLMProjectSummary(BaseModel):
    """Parsed result of a project-level LLM summary."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    description: str = ""
    frameworks: list[str] = Field(default_factory=list)
    layers: list[LLMLayer] = Field(default_factory=list)


def build_file_analysis_prompt(
    file_path: str,
    content: str,
    project_context: str,
) -> str:
    """Generate a prompt for analyzing a single source file with an LLM."""
    return f"""You are a code analysis assistant. Analyze the following source file and return a JSON object.

Project context: {project_context}

File: {file_path}

```
{content}
```

Return a JSON object with the following fields:
- "fileSummary": A concise summary of what this file does (1-2 sentences).
- "tags": An array of relevant tags (e.g., ["utility", "async", "api"]).
- "complexity": One of "simple", "moderate", or "complex".
- "functionSummaries": An object mapping function names to 1-sentence summaries.
- "classSummaries": An object mapping class names to 1-sentence summaries.
- "languageNotes": Optional notes about language-specific patterns or idioms used.

Respond ONLY with the JSON object, no additional text."""


def build_project_summary_prompt(
    file_list: list[str],
    sample_files: list[dict[str, str]],
) -> str:
    """Generate a prompt for creating a project-level summary with an LLM.

    ``sample_files`` entries are dicts with ``path`` and ``content`` keys.
    """
    file_list_str = "\n".join(f"  - {f}" for f in file_list)

    samples_str = ""
    if sample_files:
        samples_str = "\n\nSample files:\n"
        for sample in sample_files:
            samples_str += (
                f"\n--- {sample['path']} ---\n```\n{sample['content']}\n```\n"
            )

    return f"""You are a code analysis assistant. Analyze the following project structure and return a JSON object describing the project.

File list:
{file_list_str}{samples_str}

Return a JSON object with the following fields:
- "description": A concise description of what this project does (2-3 sentences).
- "frameworks": An array of frameworks and major libraries detected (e.g., ["React", "Express", "Vitest"]).
- "layers": An array of logical layers, each with:
  - "name": The layer name (e.g., "API", "Data", "UI").
  - "description": What this layer is responsible for.
  - "filePatterns": Glob patterns or path prefixes that belong to this layer.

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


def parse_file_analysis_response(response: str) -> LLMFileAnalysis | None:
    """Parse an LLM response for file analysis. Returns ``None`` on failure."""
    try:
        parsed: Any = json.loads(_extract_json(response))
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    # Validate and normalize complexity
    complexity = "moderate"
    raw_complexity = parsed.get("complexity")
    if isinstance(raw_complexity, str) and raw_complexity in VALID_COMPLEXITIES:
        complexity = raw_complexity

    tags = parsed.get("tags")
    tags_list = (
        [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []
    )

    fn_summaries = parsed.get("functionSummaries")
    cls_summaries = parsed.get("classSummaries")

    language_notes = parsed.get("languageNotes")

    return LLMFileAnalysis(
        fileSummary=parsed["fileSummary"]
        if isinstance(parsed.get("fileSummary"), str)
        else "",
        tags=tags_list,
        complexity=complexity,
        functionSummaries=fn_summaries if isinstance(fn_summaries, dict) else {},
        classSummaries=cls_summaries if isinstance(cls_summaries, dict) else {},
        languageNotes=language_notes if isinstance(language_notes, str) else None,
    )


def parse_project_summary_response(response: str) -> LLMProjectSummary | None:
    """Parse an LLM response for project summary. Returns ``None`` on failure."""
    try:
        parsed: Any = json.loads(_extract_json(response))
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    frameworks = parsed.get("frameworks")
    frameworks_list = (
        [f for f in frameworks if isinstance(f, str)]
        if isinstance(frameworks, list)
        else []
    )

    layers: list[LLMLayer] = []
    raw_layers = parsed.get("layers")
    if isinstance(raw_layers, list):
        for layer in raw_layers:
            if not isinstance(layer, dict) or not isinstance(layer.get("name"), str):
                continue
            patterns = layer.get("filePatterns")
            patterns_list = (
                [p for p in patterns if isinstance(p, str)]
                if isinstance(patterns, list)
                else []
            )
            layers.append(
                LLMLayer(
                    name=layer["name"],
                    description=layer["description"]
                    if isinstance(layer.get("description"), str)
                    else "",
                    filePatterns=patterns_list,
                )
            )

    return LLMProjectSummary(
        description=parsed["description"]
        if isinstance(parsed.get("description"), str)
        else "",
        frameworks=frameworks_list,
        layers=layers,
    )
