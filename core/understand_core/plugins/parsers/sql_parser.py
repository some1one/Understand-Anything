"""SQL parser. Port of ``plugins/parsers/sql-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_TABLE_RE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`|")?(\w+)(?:`|")?', re.IGNORECASE
)
_VIEW_RE = re.compile(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:`|")?(\w+)(?:`|")?', re.IGNORECASE
)
_INDEX_RE = re.compile(
    r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`|")?(\w+)(?:`|")?',
    re.IGNORECASE,
)
_CONSTRAINT_RE = re.compile(r"^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT|INDEX|KEY)", re.IGNORECASE)
_COL_RE = re.compile(r'^(?:`|")?(\w+)(?:`|")?\s+')


class SQLParser:
    """Extracts CREATE TABLE / VIEW / INDEX definitions."""

    name = "sql-parser"
    languages = ["sql"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(definitions=self._extract_definitions(content))

    def _extract_definitions(self, content: str) -> list[dict]:
        definitions: list[dict] = []

        for match in _TABLE_RE.finditer(content):
            table_name = match.group(1)
            start_line = content[: match.start()].count("\n") + 1
            fields = self._extract_columns(content, match.start())
            after = content[match.start() :]
            end_paren = after.find(");")
            if end_paren != -1:
                end_line = content[: match.start() + end_paren + 2].count("\n") + 1
            else:
                end_line = start_line + 5
            definitions.append(
                {"name": table_name, "kind": "table", "lineRange": [start_line, end_line], "fields": fields}
            )

        for match in _VIEW_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            definitions.append(
                {"name": match.group(1), "kind": "view", "lineRange": [start_line, start_line], "fields": []}
            )

        for match in _INDEX_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            definitions.append(
                {"name": match.group(1), "kind": "index", "lineRange": [start_line, start_line], "fields": []}
            )

        return definitions

    def _extract_columns(self, content: str, start_idx: int) -> list[str]:
        fields: list[str] = []
        after = content[start_idx:]
        open_paren = after.find("(")
        if open_paren == -1:
            return fields
        close_paren = after.find(");", open_paren)
        if close_paren == -1:
            return fields
        body = after[open_paren + 1 : close_paren]
        for line in body.split(","):
            trimmed = line.strip()
            if _CONSTRAINT_RE.match(trimmed):
                continue
            col_match = _COL_RE.match(trimmed)
            if col_match:
                fields.append(col_match.group(1))
        return fields
