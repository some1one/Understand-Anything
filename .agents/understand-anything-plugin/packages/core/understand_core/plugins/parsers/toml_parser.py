"""TOML parser. Port of ``plugins/parsers/toml-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_SECTION_RE = re.compile(r"^\s*\[(\[?)([^\]]+)\]?\]")


class TOMLParser:
    """Extracts ``[section]`` and ``[[array-of-tables]]`` headers."""

    name = "toml-parser"
    languages = ["toml"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(sections=self._extract_sections(content))

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            m = _SECTION_RE.match(line)
            if m:
                is_array = m.group(1) == "["
                name = m.group(2).strip()
                sections.append(
                    {
                        "name": f"[[{name}]]" if is_array else name,
                        "level": len(name.split(".")),
                        "lineRange": [i + 1, i + 1],
                    }
                )
        for i in range(len(sections)):
            nxt = sections[i + 1] if i + 1 < len(sections) else None
            sections[i]["lineRange"][1] = nxt["lineRange"][0] - 1 if nxt else len(lines)
        return sections
