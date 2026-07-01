"""Shell script parser. Port of ``plugins/parsers/shell-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_FUNC_PAREN_RE = re.compile(r"^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?")
_FUNC_KEYWORD_RE = re.compile(r"^function\s+(\w+)\s*\{?")
_SOURCE_RE = re.compile(r"^\s*(?:source|\.)[ \t]+[\"']?([^\"'\s]+)[\"']?")


class ShellParser:
    """Extracts shell function definitions and ``source`` references."""

    name = "shell-parser"
    languages = ["shell", "jenkinsfile"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(functions=self._extract_functions(content))

    def extract_references(self, file_path: str, content: str) -> list[dict]:
        refs: list[dict] = []
        for i, line in enumerate(content.split("\n")):
            m = _SOURCE_RE.match(line)
            if m:
                refs.append(
                    {"source": file_path, "target": m.group(1), "referenceType": "file", "line": i + 1}
                )
        return refs

    def _extract_functions(self, content: str) -> list[dict]:
        functions: list[dict] = []
        lines = content.split("\n")

        for i, line in enumerate(lines):
            match = _FUNC_PAREN_RE.match(line) or _FUNC_KEYWORD_RE.match(line)
            if not match:
                continue
            name = match.group(1)
            has_brace_here = "{" in line
            next_non_blank = i + 1
            while next_non_blank < len(lines) and lines[next_non_blank].strip() == "":
                next_non_blank += 1
            has_brace_next = (
                next_non_blank < len(lines) and lines[next_non_blank].strip().startswith("{")
            )
            if not has_brace_here and not has_brace_next:
                continue

            start_brace_line = i if has_brace_here else next_non_blank
            depth = 0
            end_line = start_brace_line
            for j in range(start_brace_line, len(lines)):
                for ch in lines[j]:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                if depth == 0:
                    end_line = j
                    break
            functions.append({"name": name, "lineRange": [i + 1, end_line + 1], "params": []})

        return functions
