""".env parser. Port of ``plugins/parsers/env-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_VAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


class EnvParser:
    """Extracts ``KEY=value`` variable definitions; skips comments / blanks.

    Does not handle ``export VAR=value`` syntax or multi-line values.
    """

    name = "env-parser"
    languages = ["env"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(definitions=self._extract_variables(content))

    def _extract_variables(self, content: str) -> list[dict]:
        definitions: list[dict] = []
        for i, raw in enumerate(content.split("\n")):
            line = raw.strip()
            if line.startswith("#") or line == "":
                continue
            m = _VAR_RE.match(line)
            if m:
                definitions.append(
                    {"name": m.group(1), "kind": "variable", "lineRange": [i + 1, i + 1], "fields": []}
                )
        return definitions
