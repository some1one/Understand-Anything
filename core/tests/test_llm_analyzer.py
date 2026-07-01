"""Port of ``analyzer/llm-analyzer.test.ts``."""

from __future__ import annotations

import json

from understand_core.analyzer.llm_analyzer import (
    build_file_analysis_prompt,
    build_project_summary_prompt,
    parse_file_analysis_response,
    parse_project_summary_response,
)


class TestBuildFileAnalysisPrompt:
    def test_includes_path_and_content(self):
        prompt = build_file_analysis_prompt(
            "src/utils.ts",
            "export function add(a: number, b: number) { return a + b; }",
            "A math utility library",
        )
        assert "src/utils.ts" in prompt
        assert "export function add" in prompt
        assert "A math utility library" in prompt
        assert "fileSummary" in prompt
        assert "JSON" in prompt

    def test_includes_project_context(self):
        prompt = build_file_analysis_prompt(
            "app.py", "print('hello')", "A Python web server"
        )
        assert "A Python web server" in prompt


class TestParseFileAnalysisResponse:
    def test_parses_valid_json(self):
        response = json.dumps(
            {
                "fileSummary": "A utility module for string processing",
                "tags": ["utility", "string"],
                "complexity": "simple",
                "functionSummaries": {"capitalize": "Capitalizes the first letter"},
                "classSummaries": {},
                "languageNotes": "Uses ES2022 features",
            }
        )
        result = parse_file_analysis_response(response)
        assert result is not None
        assert result.fileSummary == "A utility module for string processing"
        assert result.tags == ["utility", "string"]
        assert result.complexity == "simple"
        assert result.functionSummaries == {
            "capitalize": "Capitalizes the first letter"
        }
        assert result.classSummaries == {}
        assert result.languageNotes == "Uses ES2022 features"

    def test_markdown_wrapped_json(self):
        response = """Here is the analysis:

```json
{
  "fileSummary": "Database connection handler",
  "tags": ["database", "connection"],
  "complexity": "complex",
  "functionSummaries": { "connect": "Establishes DB connection" },
  "classSummaries": { "Pool": "Connection pool manager" }
}
```

That's the analysis."""
        result = parse_file_analysis_response(response)
        assert result is not None
        assert result.fileSummary == "Database connection handler"
        assert result.tags == ["database", "connection"]
        assert result.complexity == "complex"
        assert result.functionSummaries["connect"] == "Establishes DB connection"
        assert result.classSummaries["Pool"] == "Connection pool manager"

    def test_markdown_fences_without_language_tag(self):
        response = """```
{
  "fileSummary": "Config loader",
  "tags": ["config"],
  "complexity": "simple",
  "functionSummaries": {},
  "classSummaries": {}
}
```"""
        result = parse_file_analysis_response(response)
        assert result is not None
        assert result.fileSummary == "Config loader"

    def test_null_for_invalid_json(self):
        assert parse_file_analysis_response("This is not JSON at all") is None

    def test_null_for_empty(self):
        assert parse_file_analysis_response("") is None

    def test_default_complexity_for_unknown(self):
        response = json.dumps(
            {
                "fileSummary": "Some file",
                "tags": [],
                "complexity": "very-hard",
                "functionSummaries": {},
                "classSummaries": {},
            }
        )
        result = parse_file_analysis_response(response)
        assert result is not None
        assert result.complexity == "moderate"

    def test_default_complexity_when_missing(self):
        response = json.dumps(
            {
                "fileSummary": "Some file",
                "tags": [],
                "functionSummaries": {},
                "classSummaries": {},
            }
        )
        result = parse_file_analysis_response(response)
        assert result is not None
        assert result.complexity == "moderate"

    def test_missing_optional_fields(self):
        response = json.dumps({"fileSummary": "Minimal response"})
        result = parse_file_analysis_response(response)
        assert result is not None
        assert result.fileSummary == "Minimal response"
        assert result.tags == []
        assert result.complexity == "moderate"
        assert result.functionSummaries == {}
        assert result.classSummaries == {}
        assert result.languageNotes is None


class TestBuildProjectSummaryPrompt:
    def test_includes_file_list(self):
        file_list = ["src/index.ts", "src/utils.ts", "package.json"]
        prompt = build_project_summary_prompt(file_list, [])
        assert "src/index.ts" in prompt
        assert "src/utils.ts" in prompt
        assert "package.json" in prompt
        assert "description" in prompt
        assert "frameworks" in prompt
        assert "layers" in prompt

    def test_includes_sample_file_contents(self):
        prompt = build_project_summary_prompt(
            ["src/app.ts"],
            [{"path": "src/app.ts", "content": "const app = express();"}],
        )
        assert "src/app.ts" in prompt
        assert "const app = express()" in prompt


class TestParseProjectSummaryResponse:
    def test_parses_valid_summary(self):
        response = json.dumps(
            {
                "description": "A REST API for managing tasks",
                "frameworks": ["Express", "TypeScript", "Vitest"],
                "layers": [
                    {
                        "name": "API",
                        "description": "HTTP route handlers",
                        "filePatterns": ["src/routes/**"],
                    },
                    {
                        "name": "Data",
                        "description": "Database access layer",
                        "filePatterns": ["src/db/**", "src/models/**"],
                    },
                ],
            }
        )
        result = parse_project_summary_response(response)
        assert result is not None
        assert result.description == "A REST API for managing tasks"
        assert result.frameworks == ["Express", "TypeScript", "Vitest"]
        assert len(result.layers) == 2
        assert result.layers[0].model_dump() == {
            "name": "API",
            "description": "HTTP route handlers",
            "filePatterns": ["src/routes/**"],
        }

    def test_markdown_wrapped(self):
        response = """```json
{
  "description": "A CLI tool",
  "frameworks": ["Commander"],
  "layers": []
}
```"""
        result = parse_project_summary_response(response)
        assert result is not None
        assert result.description == "A CLI tool"
        assert result.frameworks == ["Commander"]

    def test_null_for_invalid_json(self):
        assert parse_project_summary_response("Not valid JSON") is None

    def test_missing_fields(self):
        response = json.dumps({"description": "Some project"})
        result = parse_project_summary_response(response)
        assert result is not None
        assert result.description == "Some project"
        assert result.frameworks == []
        assert result.layers == []
