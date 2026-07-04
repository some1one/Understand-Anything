"""GraphQL schema parser. Port of ``plugins/parsers/graphql-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_TYPE_RE = re.compile(r"^(type|input|enum|interface|union|scalar)\s+(\w+)", re.MULTILINE)
_BLOCK_RE = re.compile(r"^(type)\s+(Query|Mutation|Subscription)\s*\{", re.MULTILINE)
_WORD_RE = re.compile(r"^(\w+)")


class GraphQLParser:
    """Extracts type/input/enum/interface/union/scalar defs and root endpoints."""

    name = "graphql-parser"
    languages = ["graphql"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(
            definitions=self._extract_definitions(content),
            endpoints=self._extract_endpoints(content),
        )

    def _extract_definitions(self, content: str) -> list[dict]:
        definitions: list[dict] = []
        for match in _TYPE_RE.finditer(content):
            kind = match.group(1)
            name = match.group(2)
            if name in ("Query", "Mutation", "Subscription"):
                continue
            start_line = content[: match.start()].count("\n") + 1
            fields = self._extract_fields(content, match.start())
            after = content[match.start() :]
            close_brace = after.find("}")
            if close_brace != -1:
                end_line = content[: match.start() + close_brace + 1].count("\n") + 1
            else:
                end_line = start_line
            definitions.append(
                {"name": name, "kind": kind, "lineRange": [start_line, end_line], "fields": fields}
            )
        return definitions

    def _extract_endpoints(self, content: str) -> list[dict]:
        endpoints: list[dict] = []
        for match in _BLOCK_RE.finditer(content):
            method = match.group(2)
            start_idx = match.end()
            depth = 1
            i = start_idx
            while i < len(content) and depth > 0:
                if content[i] == "{":
                    depth += 1
                if content[i] == "}":
                    depth -= 1
                i += 1
            block_content = content[start_idx : i - 1]
            block_lines = block_content.split("\n")
            block_start_line = content[:start_idx].count("\n") + 1
            for j, line in enumerate(block_lines):
                field_match = _WORD_RE.match(line.strip())
                if field_match and field_match.group(1):
                    line_num = block_start_line + j
                    endpoints.append(
                        {"method": method, "path": field_match.group(1), "lineRange": [line_num, line_num]}
                    )
        return endpoints

    def _extract_fields(self, content: str, start_idx: int) -> list[str]:
        fields: list[str] = []
        after = content[start_idx:]
        open_brace = after.find("{")
        if open_brace == -1:
            return fields
        depth = 1
        i = open_brace + 1
        while i < len(after) and depth > 0:
            if after[i] == "{":
                depth += 1
            if after[i] == "}":
                depth -= 1
            i += 1
        body = after[open_brace + 1 : i - 1]
        for line in body.split("\n"):
            field_match = _WORD_RE.match(line.strip())
            if field_match:
                fields.append(field_match.group(1))
        return fields
