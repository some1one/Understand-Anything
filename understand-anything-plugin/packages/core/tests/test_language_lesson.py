"""Port of ``__tests__/language-lesson.test.ts``.

The TS test imports ``typescriptConfig`` from the languages cluster (ported in a
separate cluster). To keep this test self-contained, a minimal stand-in config
carrying the same ``displayName``/``concepts`` shape is used; the lesson code
reads those fields by attribute or key, so behaviour is identical.
"""

from __future__ import annotations

import json

from understand_core.analyzer.language_lesson import (
    build_language_lesson_prompt,
    detect_language_concepts,
    parse_language_lesson_response,
)
from understand_core.types import GraphEdge, GraphNode

# Stand-in for languages/configs/typescript.typescriptConfig
typescript_config = {
    "id": "typescript",
    "displayName": "TypeScript",
    "concepts": ["generics", "type guards", "decorators"],
}

sample_node = GraphNode.model_construct(
    id="function:auth:verifyToken",
    type="function",
    name="verifyToken",
    filePath="src/auth/verify.ts",
    lineRange=[10, 35],
    summary="Verifies JWT tokens and extracts user payload using async/await",
    tags=["auth", "jwt", "async"],
    complexity="moderate",
)

sample_edges = [
    GraphEdge.model_construct(
        source="function:auth:verifyToken",
        target="file:src/config.ts",
        type="reads_from",
        direction="forward",
        weight=0.6,
    ),
    GraphEdge.model_construct(
        source="file:src/middleware.ts",
        target="function:auth:verifyToken",
        type="calls",
        direction="forward",
        weight=0.8,
    ),
]


class TestBuildLanguageLessonPrompt:
    def test_includes_name_and_summary(self):
        prompt = build_language_lesson_prompt(sample_node, sample_edges, "typescript")
        assert "verifyToken" in prompt
        assert "JWT tokens" in prompt

    def test_includes_target_language(self):
        prompt = build_language_lesson_prompt(
            sample_node, sample_edges, "typescript", typescript_config
        )
        assert "TypeScript" in prompt

    def test_includes_relationship_context(self):
        prompt = build_language_lesson_prompt(sample_node, sample_edges, "typescript")
        assert "reads_from" in prompt

    def test_requests_json(self):
        prompt = build_language_lesson_prompt(sample_node, sample_edges, "typescript")
        assert "JSON" in prompt


class TestParseLanguageLessonResponse:
    def test_valid_response(self):
        response = json.dumps(
            {
                "languageNotes": "Uses async/await for non-blocking token verification.",
                "concepts": [
                    {
                        "name": "async/await",
                        "explanation": "The function uses async/await to handle asynchronous JWT verification.",
                    }
                ],
            }
        )
        result = parse_language_lesson_response(response)
        assert result.languageNotes == (
            "Uses async/await for non-blocking token verification."
        )
        assert len(result.concepts) == 1
        assert result.concepts[0].name == "async/await"
        assert "async/await" in result.concepts[0].explanation

    def test_extracts_from_code_blocks(self):
        response = """Here is the analysis:
```json
{
  "languageNotes": "TypeScript generics used here.",
  "concepts": [
    { "name": "generics", "explanation": "Type parameters enable reuse." }
  ]
}
```"""
        result = parse_language_lesson_response(response)
        assert result.languageNotes == "TypeScript generics used here."
        assert len(result.concepts) == 1
        assert result.concepts[0].name == "generics"

    def test_empty_for_invalid(self):
        result = parse_language_lesson_response("")
        assert result.languageNotes == ""
        assert result.concepts == []


class TestDetectLanguageConcepts:
    def test_async_from_tags(self):
        concepts = detect_language_concepts(sample_node, "typescript")
        assert "async/await" in concepts

    def test_middleware_pattern(self):
        middleware_node = GraphNode.model_construct(
            id="function:middleware:auth",
            type="function",
            name="authMiddleware",
            filePath="src/middleware/auth.ts",
            summary="Express middleware for authentication",
            tags=["middleware", "auth"],
            complexity="moderate",
        )
        concepts = detect_language_concepts(middleware_node, "typescript")
        assert "middleware pattern" in concepts

    def test_no_detectable_concepts(self):
        plain_node = GraphNode.model_construct(
            id="file:src/config.ts",
            type="file",
            name="config.ts",
            filePath="src/config.ts",
            summary="Exports configuration values from environment variables",
            tags=["config"],
            complexity="simple",
        )
        concepts = detect_language_concepts(plain_node, "typescript")
        assert concepts == []
