"""Markdown parser. Port of ``plugins/parsers/markdown-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")


class MarkdownParser:
    """Extracts heading sections and local file/image references."""

    name = "markdown-parser"
    languages = ["markdown"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(sections=self._extract_sections(content))

    def extract_references(self, file_path: str, content: str) -> list[dict]:
        refs: list[dict] = []
        for match in _LINK_RE.finditer(content):
            target = match.group(2)
            if target.startswith("http"):
                continue
            line = content[: match.start()].count("\n") + 1
            refs.append(
                {
                    "source": file_path,
                    "target": target,
                    "referenceType": "image" if match.group(0).startswith("!") else "file",
                    "line": line,
                }
            )
        return refs

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        lines = content.split("\n")
        in_fence = False
        fence_marker: str | None = None
        for i, line in enumerate(lines):
            fence_match = _FENCE_RE.match(line)
            if fence_match:
                if not in_fence:
                    in_fence = True
                    fence_marker = fence_match.group(1)[0]
                elif fence_marker and line.startswith(fence_marker):
                    in_fence = False
                    fence_marker = None
                continue
            if in_fence:
                continue
            heading = _HEADING_RE.match(line)
            if heading:
                sections.append(
                    {
                        "name": heading.group(2).strip(),
                        "level": len(heading.group(1)),
                        "lineRange": [i + 1, i + 1],
                    }
                )
        for i in range(len(sections)):
            nxt = sections[i + 1] if i + 1 < len(sections) else None
            sections[i]["lineRange"][1] = nxt["lineRange"][0] - 1 if nxt else len(lines)
        return sections
