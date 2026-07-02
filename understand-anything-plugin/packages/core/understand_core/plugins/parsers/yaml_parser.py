"""YAML config parser. Port of ``plugins/parsers/yaml-parser.ts`` (uses pyyaml)."""

from __future__ import annotations

import re

import yaml

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_REGEX_KEY = re.compile(r"^(\w[\w-]*)\s*:")


class YAMLConfigParser:
    """Extracts top-level key sections from YAML and YAML-flavored formats."""

    name = "yaml-config-parser"
    languages = ["yaml", "kubernetes", "docker-compose", "github-actions", "openapi"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(sections=self._extract_sections(content))

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        lines = content.split("\n")
        try:
            doc = yaml.safe_load(content)
        except yaml.YAMLError:
            # Regex fallback for malformed YAML.
            for i, line in enumerate(lines):
                m = _REGEX_KEY.match(line)
                if m:
                    sections.append({"name": m.group(1), "level": 1, "lineRange": [i + 1, i + 1]})
            self._fix_ranges(sections, len(lines))
            return sections

        if isinstance(doc, dict):
            for key in doc.keys():
                escaped = re.escape(str(key))
                pattern = re.compile(rf"^[\"']?{escaped}[\"']?\s*:")
                line_idx = next((j for j, l in enumerate(lines) if pattern.match(l)), -1)
                if line_idx != -1:
                    sections.append(
                        {"name": str(key), "level": 1, "lineRange": [line_idx + 1, line_idx + 1]}
                    )
            self._fix_ranges(sections, len(lines))
        elif isinstance(doc, list):
            for i, entry in enumerate(doc):
                name = f"[{i}]"
                if isinstance(entry, dict):
                    for field in ("name", "id", "kind"):
                        if isinstance(entry.get(field), str):
                            name = entry[field]
                            break
                sections.append({"name": name, "level": 1, "lineRange": [1, len(lines)]})
        return sections

    @staticmethod
    def _fix_ranges(sections: list[dict], total: int) -> None:
        for i in range(len(sections)):
            nxt = sections[i + 1] if i + 1 < len(sections) else None
            sections[i]["lineRange"][1] = nxt["lineRange"][0] - 1 if nxt else total
