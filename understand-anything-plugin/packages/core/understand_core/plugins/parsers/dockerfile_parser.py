"""Dockerfile parser. Port of ``plugins/parsers/dockerfile-parser.ts``."""

from __future__ import annotations

import re

from understand_core.plugins.parsers._result import StructuralAnalysisResult, make_analysis

_FROM_LINE_RE = re.compile(r"^FROM\s+", re.IGNORECASE)
_FROM_RE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE)
_EXPOSE_RE = re.compile(r"^EXPOSE\s+(.+)", re.IGNORECASE)
_STEP_RE = re.compile(
    r"^(FROM|RUN|COPY|ADD|WORKDIR|CMD|ENTRYPOINT|ENV|ARG|EXPOSE|VOLUME|USER|HEALTHCHECK)\s",
    re.IGNORECASE,
)


class DockerfileParser:
    """Extracts multi-stage FROM stages, EXPOSE ports, and instruction steps."""

    name = "dockerfile-parser"
    languages = ["dockerfile"]

    def analyze_file(self, _file_path: str, content: str) -> StructuralAnalysisResult:
        return make_analysis(
            services=self._extract_stages(content), steps=self._extract_steps(content)
        )

    def _extract_stages(self, content: str) -> list[dict]:
        stages: list[dict] = []
        lines = content.split("\n")

        from_lines = [i for i, l in enumerate(lines) if _FROM_LINE_RE.match(l)]

        for s, stage_start in enumerate(from_lines):
            stage_end = from_lines[s + 1] - 1 if s + 1 < len(from_lines) else len(lines) - 1
            from_match = _FROM_RE.match(lines[stage_start])
            if not from_match:
                continue
            image = from_match.group(1)
            if from_match.group(2):
                name = from_match.group(2)
            else:
                name = image.split(":")[0].split("/")[-1] or image

            ports: list[int] = []
            for i in range(stage_start, stage_end + 1):
                expose_match = _EXPOSE_RE.match(lines[i])
                if expose_match:
                    for p in re.split(r"\s+", expose_match.group(1)):
                        try:
                            ports.append(int(p))
                        except ValueError:
                            pass

            stages.append(
                {
                    "name": name,
                    "image": image,
                    "ports": ports,
                    "lineRange": [stage_start + 1, stage_end + 1],
                }
            )

        return stages

    def _extract_steps(self, content: str) -> list[dict]:
        steps: list[dict] = []
        for i, line in enumerate(content.split("\n")):
            m = _STEP_RE.match(line)
            if m:
                instr = m.group(1)
                rest = line[len(instr) + 1 :].strip()[:60]
                steps.append({"name": f"{instr.upper()} {rest}", "lineRange": [i + 1, i + 1]})
        return steps
