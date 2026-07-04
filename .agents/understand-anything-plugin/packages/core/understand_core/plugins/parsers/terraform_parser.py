"""Terraform (HCL) parser. Port of ``plugins/parsers/terraform-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_RESOURCE_RE = re.compile(r'^resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', re.MULTILINE)
_DATA_RE = re.compile(r'^data\s+"([^"]+)"\s+"([^"]+)"\s*\{', re.MULTILINE)
_MODULE_RE = re.compile(r'^module\s+"([^"]+)"\s*\{', re.MULTILINE)
_VAR_RE = re.compile(r'^variable\s+"([^"]+)"\s*\{', re.MULTILINE)
_OUTPUT_RE = re.compile(r'^output\s+"([^"]+)"\s*\{', re.MULTILINE)


class TerraformParser:
    """Extracts resource/data/module blocks and variable/output definitions."""

    name = "terraform-parser"
    languages = ["terraform"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(
            resources=self._extract_resources(content),
            definitions=self._extract_variables_and_outputs(content),
        )

    def _block_end_line(self, content: str, start: int) -> int:
        after = content[start:]
        close_brace = self._find_closing_brace(after)
        return content[: start + close_brace + 1].count("\n") + 1

    def _extract_resources(self, content: str) -> list[dict]:
        resources: list[dict] = []

        for match in _RESOURCE_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            end_line = self._block_end_line(content, match.start())
            resources.append(
                {"name": f"{match.group(1)}.{match.group(2)}", "kind": match.group(1), "lineRange": [start_line, end_line]}
            )

        for match in _DATA_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            end_line = self._block_end_line(content, match.start())
            resources.append(
                {
                    "name": f"data.{match.group(1)}.{match.group(2)}",
                    "kind": f"data.{match.group(1)}",
                    "lineRange": [start_line, end_line],
                }
            )

        for match in _MODULE_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            end_line = self._block_end_line(content, match.start())
            resources.append(
                {"name": f"module.{match.group(1)}", "kind": "module", "lineRange": [start_line, end_line]}
            )

        return resources

    def _extract_variables_and_outputs(self, content: str) -> list[dict]:
        definitions: list[dict] = []

        for match in _VAR_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            end_line = self._block_end_line(content, match.start())
            definitions.append(
                {"name": match.group(1), "kind": "variable", "lineRange": [start_line, end_line], "fields": []}
            )

        for match in _OUTPUT_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            end_line = self._block_end_line(content, match.start())
            definitions.append(
                {"name": match.group(1), "kind": "output", "lineRange": [start_line, end_line], "fields": []}
            )

        return definitions

    @staticmethod
    def _find_closing_brace(content: str) -> int:
        depth = 0
        for i, ch in enumerate(content):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        return len(content)
