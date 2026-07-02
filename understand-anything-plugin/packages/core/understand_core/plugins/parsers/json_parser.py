"""JSON / JSONC config parser. Port of ``plugins/parsers/json-parser.ts``."""

from __future__ import annotations

import json
import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_REF_RE = re.compile(r'"\$ref"\s*:\s*"([^"]+)"')


def strip_jsonc_syntax(content: str) -> str:
    """Strip JSONC line/block comments and trailing commas. Strings preserved."""
    out: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""

        # String literal — copy verbatim, honoring escapes.
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                c = content[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(content[i + 1])
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
            continue

        # Line comment.
        if ch == "/" and nxt == "/":
            i += 2
            while i < n and content[i] != "\n":
                i += 1
            continue

        # Block comment.
        if ch == "/" and nxt == "*":
            i += 2
            while i < n and not (content[i] == "*" and i + 1 < n and content[i + 1] == "/"):
                i += 1
            i += 2
            continue

        out.append(ch)
        i += 1

    return _TRAILING_COMMA_RE.sub(r"\1", "".join(out))


class JSONConfigParser:
    """Extracts top-level keys and ``$ref`` references from JSON/JSONC files."""

    name = "json-config-parser"
    languages = ["json", "jsonc", "json-schema", "openapi"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(sections=self._extract_sections(content))

    def extract_references(self, file_path: str, content: str) -> list[dict]:
        refs: list[dict] = []
        for match in _REF_RE.finditer(content):
            target = match.group(1)
            if target.startswith("#"):
                continue
            line = content[: match.start()].count("\n") + 1
            refs.append(
                {"source": file_path, "target": target, "referenceType": "schema", "line": line}
            )
        return refs

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        try:
            doc = json.loads(strip_jsonc_syntax(content))
        except (ValueError, TypeError):
            return sections
        if isinstance(doc, dict):
            lines = content.split("\n")
            for key in doc.keys():
                escaped_key = json.dumps(key)
                line_idx = next((i for i, l in enumerate(lines) if escaped_key in l), -1)
                if line_idx != -1:
                    sections.append(
                        {"name": key, "level": 1, "lineRange": [line_idx + 1, line_idx + 1]}
                    )
            for i in range(len(sections)):
                nxt = sections[i + 1] if i + 1 < len(sections) else None
                sections[i]["lineRange"][1] = nxt["lineRange"][0] - 1 if nxt else len(lines)
        return sections
