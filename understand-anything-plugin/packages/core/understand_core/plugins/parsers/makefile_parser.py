"""Makefile parser. Port of ``plugins/parsers/makefile-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_TARGET_RE = re.compile(r"^([a-zA-Z_.][a-zA-Z0-9_.-]*)(?:\s+.*)?:")


class MakefileParser:
    """Extracts build targets; filters special targets and variable assignments."""

    name = "makefile-parser"
    languages = ["makefile"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(steps=self._extract_targets(content))

    def _extract_targets(self, content: str) -> list[dict]:
        targets: list[dict] = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            m = _TARGET_RE.match(line)
            if m and ":=" not in line and "?=" not in line:
                name = m.group(1)
                if name.startswith("."):
                    continue
                end_line = i + 1
                while end_line < len(lines):
                    nxt = lines[end_line]
                    if nxt == "" or nxt.startswith("\t") or nxt.startswith("  "):
                        end_line += 1
                    else:
                        break
                targets.append({"name": name, "lineRange": [i + 1, end_line]})
        return targets
