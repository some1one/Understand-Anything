"""Protocol Buffer parser. Port of ``plugins/parsers/protobuf-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_MESSAGE_RE = re.compile(r"^message\s+(\w+)\s*\{", re.MULTILINE)
_ENUM_RE = re.compile(r"^enum\s+(\w+)\s*\{", re.MULTILINE)
_SERVICE_RE = re.compile(r"^service\s+(\w+)\s*\{", re.MULTILINE)
_RPC_RE = re.compile(r"rpc\s+(\w+)\s*\(")
_FIELD_RE = re.compile(
    r"^\s*(?:repeated\s+|optional\s+|required\s+|map<[^>]+>\s+)?\w+\s+(\w+)\s*=", re.MULTILINE
)
_ENUM_VALUE_RE = re.compile(r"^\s*(\w+)\s*=", re.MULTILINE)


class ProtobufParser:
    """Extracts message/enum definitions and service RPC method endpoints."""

    name = "protobuf-parser"
    languages = ["protobuf"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(
            definitions=self._extract_definitions(content),
            endpoints=self._extract_service_methods(content),
        )

    def _extract_definitions(self, content: str) -> list[dict]:
        definitions: list[dict] = []

        for match in _MESSAGE_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            fields = self._extract_message_fields(content, match.start())
            after = content[match.start() :]
            close_brace = self._find_closing_brace(after)
            end_line = content[: match.start() + close_brace + 1].count("\n") + 1
            definitions.append(
                {"name": match.group(1), "kind": "message", "lineRange": [start_line, end_line], "fields": fields}
            )

        for match in _ENUM_RE.finditer(content):
            start_line = content[: match.start()].count("\n") + 1
            fields = self._extract_enum_values(content, match.start())
            after = content[match.start() :]
            close_brace = self._find_closing_brace(after)
            end_line = content[: match.start() + close_brace + 1].count("\n") + 1
            definitions.append(
                {"name": match.group(1), "kind": "enum", "lineRange": [start_line, end_line], "fields": fields}
            )

        return definitions

    def _extract_service_methods(self, content: str) -> list[dict]:
        endpoints: list[dict] = []
        for match in _SERVICE_RE.finditer(content):
            service_name = match.group(1)
            start_idx = match.end()
            after_service = content[match.start() :]
            close_brace = self._find_closing_brace(after_service)
            body = after_service[len(match.group(0)) : close_brace]
            for rpc_match in _RPC_RE.finditer(body):
                line_num = content[: start_idx + rpc_match.start()].count("\n") + 1
                endpoints.append(
                    {"method": "rpc", "path": f"{service_name}.{rpc_match.group(1)}", "lineRange": [line_num, line_num]}
                )
        return endpoints

    def _extract_message_fields(self, content: str, start_idx: int) -> list[str]:
        after = content[start_idx:]
        open_brace = after.find("{")
        if open_brace == -1:
            return []
        close_brace = self._find_closing_brace(after)
        body = after[open_brace + 1 : close_brace]
        return [m.group(1) for m in _FIELD_RE.finditer(body)]

    def _extract_enum_values(self, content: str, start_idx: int) -> list[str]:
        after = content[start_idx:]
        open_brace = after.find("{")
        if open_brace == -1:
            return []
        close_brace = self._find_closing_brace(after)
        body = after[open_brace + 1 : close_brace]
        return [m.group(1) for m in _ENUM_VALUE_RE.finditer(body)]

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
