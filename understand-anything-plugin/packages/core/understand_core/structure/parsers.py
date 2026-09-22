"""Non-code parsers (port of core/src/plugins/parsers/*.ts).

These are hand-written regex/line parsers, NOT tree-sitter. They mirror the
TypeScript parsers' behavior. Each parser exposes ``languages`` (the language
ids it registers for) and ``analyze_file(content) -> StructuralAnalysis``.

JS idiom note: ``content.slice(0, idx).split("\\n").length`` returns the 1-based
line number of the character at ``idx`` — i.e. ``content[:idx].count("\\n") + 1``.
"""

from __future__ import annotations

import json
import re

from .base import StructuralAnalysis


def _line_of(content: str, idx: int) -> int:
    """1-based line number for character offset ``idx`` (JS slice/split idiom)."""
    return content[:idx].count("\n") + 1


def _make_section(name: str, level: int, line_range: list[int]) -> dict:
    return {"name": name, "level": level, "lineRange": line_range}


def _make_definition(name: str, kind: str, line_range: list[int], fields: list[str]) -> dict:
    return {"name": name, "kind": kind, "lineRange": line_range, "fields": fields}


def _make_service(name: str, image, ports: list[int], line_range: list[int] | None) -> dict:
    s: dict = {"name": name, "image": image, "ports": ports}
    if line_range is not None:
        s["lineRange"] = line_range
    return s


def _make_endpoint(method, path: str, line_range: list[int]) -> dict:
    return {"method": method, "path": path, "lineRange": line_range}


def _make_step(name: str, line_range: list[int]) -> dict:
    return {"name": name, "lineRange": line_range}


def _make_resource(name: str, kind: str, line_range: list[int]) -> dict:
    return {"name": name, "kind": kind, "lineRange": line_range}


def _fix_section_ends(sections: list[dict], total_lines: int) -> None:
    """End each section's range at next section start - 1, else EOF."""
    for i in range(len(sections)):
        nxt = sections[i + 1] if i + 1 < len(sections) else None
        sections[i]["lineRange"][1] = nxt["lineRange"][0] - 1 if nxt else total_lines


# ===========================================================================
# Markdown
# ===========================================================================


class MarkdownParser:
    languages = ["markdown"]
    _fence_re = re.compile(r"^(```+|~~~+)")
    _heading_re = re.compile(r"^(#{1,6})\s+(.+)")

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(sections=self._extract_sections(content))

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        lines = content.split("\n")
        in_fence = False
        fence_marker: str | None = None
        for i, line in enumerate(lines):
            fence_match = self._fence_re.match(line)
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
            m = self._heading_re.match(line)
            if m:
                sections.append(_make_section(m.group(2).strip(), len(m.group(1)), [i + 1, i + 1]))
        _fix_section_ends(sections, len(lines))
        return sections


# ===========================================================================
# YAML
# ===========================================================================


class YAMLConfigParser:
    languages = ["yaml", "kubernetes", "docker-compose", "github-actions", "openapi"]
    _regex_key_re = re.compile(r"^(\w[\w-]*)\s*:")

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(sections=self._extract_sections(content))

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        try:
            import yaml

            doc = yaml.safe_load(content)
            lines = content.split("\n")
            if isinstance(doc, dict):
                for key in doc.keys():
                    key_str = str(key)
                    escaped = re.escape(key_str)
                    pattern = re.compile(rf'^["\']?{escaped}["\']?\s*:')
                    line_idx = next((j for j, ln in enumerate(lines) if pattern.search(ln)), -1)
                    if line_idx != -1:
                        sections.append(_make_section(key_str, 1, [line_idx + 1, line_idx + 1]))
                _fix_section_ends(sections, len(lines))
            elif isinstance(doc, list):
                for i, entry in enumerate(doc):
                    name = f"[{i}]"
                    if isinstance(entry, dict):
                        for field_key in ("name", "id", "kind"):
                            if isinstance(entry.get(field_key), str):
                                name = entry[field_key]
                                break
                    sections.append(_make_section(name, 1, [1, len(lines)]))
            return sections
        except Exception:
            # Regex fallback (matches the JS catch branch).
            sections = []
            lines = content.split("\n")
            for i, line in enumerate(lines):
                m = self._regex_key_re.match(line)
                if m:
                    sections.append(_make_section(m.group(1), 1, [i + 1, i + 1]))
            _fix_section_ends(sections, len(lines))
            return sections


# ===========================================================================
# JSON / JSONC
# ===========================================================================


def strip_jsonc_syntax(content: str) -> str:
    """Strip JSONC comments + trailing commas (port of stripJsoncSyntax)."""
    out: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""
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
        if ch == "/" and nxt == "/":
            i += 2
            while i < n and content[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i < n and not (content[i] == "*" and (i + 1 < n and content[i + 1] == "/")):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


class JSONConfigParser:
    languages = ["json", "jsonc", "json-schema", "openapi"]

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(sections=self._extract_sections(content))

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        try:
            doc = json.loads(strip_jsonc_syntax(content))
        except Exception:
            return sections
        if isinstance(doc, dict):
            lines = content.split("\n")
            for key in doc.keys():
                escaped_key = json.dumps(key)
                line_idx = next((j for j, ln in enumerate(lines) if escaped_key in ln), -1)
                if line_idx != -1:
                    sections.append(_make_section(key, 1, [line_idx + 1, line_idx + 1]))
            _fix_section_ends(sections, len(lines))
        return sections


# ===========================================================================
# TOML
# ===========================================================================


class TOMLParser:
    languages = ["toml"]
    _section_re = re.compile(r"^\s*\[(\[?)([^\]]+)\]?\]")

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(sections=self._extract_sections(content))

    def _extract_sections(self, content: str) -> list[dict]:
        sections: list[dict] = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            m = self._section_re.match(line)
            if m:
                is_array = m.group(1) == "["
                name = m.group(2).strip()
                sections.append(
                    _make_section(f"[[{name}]]" if is_array else name, len(name.split(".")), [i + 1, i + 1])
                )
        _fix_section_ends(sections, len(lines))
        return sections


# ===========================================================================
# .env
# ===========================================================================


class EnvParser:
    languages = ["env"]
    _var_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(definitions=self._extract_variables(content))

    def _extract_variables(self, content: str) -> list[dict]:
        definitions: list[dict] = []
        for i, raw in enumerate(content.split("\n")):
            line = raw.strip()
            if line.startswith("#") or line == "":
                continue
            m = self._var_re.match(line)
            if m:
                definitions.append(_make_definition(m.group(1), "variable", [i + 1, i + 1], []))
        return definitions


# ===========================================================================
# Dockerfile
# ===========================================================================


class DockerfileParser:
    languages = ["dockerfile"]
    _from_re = re.compile(r"^FROM\s+", re.IGNORECASE)
    _from_detail_re = re.compile(r"^FROM\s+(\S+)(?:\s+[Aa][Ss]\s+(\S+))?", re.IGNORECASE)
    _expose_re = re.compile(r"^EXPOSE\s+(.+)", re.IGNORECASE)
    _step_re = re.compile(
        r"^(FROM|RUN|COPY|ADD|WORKDIR|CMD|ENTRYPOINT|ENV|ARG|EXPOSE|VOLUME|USER|HEALTHCHECK)\s",
        re.IGNORECASE,
    )

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(
            services=self._extract_stages(content), steps=self._extract_steps(content)
        )

    def _extract_stages(self, content: str) -> list[dict]:
        stages: list[dict] = []
        lines = content.split("\n")
        from_lines = [i for i, line in enumerate(lines) if self._from_re.match(line)]
        for s, stage_start in enumerate(from_lines):
            stage_end = from_lines[s + 1] - 1 if s + 1 < len(from_lines) else len(lines) - 1
            from_match = self._from_detail_re.match(lines[stage_start])
            if not from_match:
                continue
            image = from_match.group(1)
            name = from_match.group(2)
            if not name:
                name = image.split(":")[0].split("/")[-1] or image
            ports: list[int] = []
            for i in range(stage_start, stage_end + 1):
                expose_match = self._expose_re.match(lines[i])
                if expose_match:
                    for p in re.split(r"\s+", expose_match.group(1)):
                        try:
                            ports.append(int(p))
                        except ValueError:
                            pass
            stages.append(_make_service(name, image, ports, [stage_start + 1, stage_end + 1]))
        return stages

    def _extract_steps(self, content: str) -> list[dict]:
        steps: list[dict] = []
        for i, line in enumerate(content.split("\n")):
            m = self._step_re.match(line)
            if m:
                kw = m.group(1)
                rest = line[len(kw) + 1:].strip()[:60]
                steps.append(_make_step(f"{kw.upper()} {rest}", [i + 1, i + 1]))
        return steps


# ===========================================================================
# SQL
# ===========================================================================


class SQLParser:
    languages = ["sql"]
    _table_re = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`|")?(\w+)(?:`|")?', re.IGNORECASE)
    _view_re = re.compile(r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:`|")?(\w+)(?:`|")?', re.IGNORECASE)
    _index_re = re.compile(
        r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`|")?(\w+)(?:`|")?', re.IGNORECASE
    )
    _constraint_re = re.compile(r"^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT|INDEX|KEY)", re.IGNORECASE)
    _col_re = re.compile(r'^(?:`|")?(\w+)(?:`|")?\s+')

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(definitions=self._extract_definitions(content))

    def _extract_definitions(self, content: str) -> list[dict]:
        definitions: list[dict] = []
        for m in self._table_re.finditer(content):
            start_line = _line_of(content, m.start())
            fields = self._extract_columns(content, m.start())
            after = content[m.start():]
            end_paren = after.find(");")
            end_line = _line_of(content, m.start() + end_paren + 2) if end_paren != -1 else start_line + 5
            definitions.append(_make_definition(m.group(1), "table", [start_line, end_line], fields))
        for m in self._view_re.finditer(content):
            start_line = _line_of(content, m.start())
            definitions.append(_make_definition(m.group(1), "view", [start_line, start_line], []))
        for m in self._index_re.finditer(content):
            start_line = _line_of(content, m.start())
            definitions.append(_make_definition(m.group(1), "index", [start_line, start_line], []))
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
        body = after[open_paren + 1:close_paren]
        for segment in body.split(","):
            trimmed = segment.strip()
            if self._constraint_re.match(trimmed):
                continue
            cm = self._col_re.match(trimmed)
            if cm:
                fields.append(cm.group(1))
        return fields


# ===========================================================================
# GraphQL
# ===========================================================================


class GraphQLParser:
    languages = ["graphql"]
    _type_re = re.compile(r"^(type|input|enum|interface|union|scalar)\s+(\w+)", re.MULTILINE)
    _block_re = re.compile(r"^(type)\s+(Query|Mutation|Subscription)\s*\{", re.MULTILINE)
    _word_re = re.compile(r"^(\w+)")

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(
            definitions=self._extract_definitions(content), endpoints=self._extract_endpoints(content)
        )

    def _extract_definitions(self, content: str) -> list[dict]:
        definitions: list[dict] = []
        for m in self._type_re.finditer(content):
            kind = m.group(1)
            name = m.group(2)
            if name in ("Query", "Mutation", "Subscription"):
                continue
            start_line = _line_of(content, m.start())
            fields = self._extract_fields(content, m.start())
            after = content[m.start():]
            close_brace = after.find("}")
            end_line = _line_of(content, m.start() + close_brace + 1) if close_brace != -1 else start_line
            definitions.append(_make_definition(name, kind, [start_line, end_line], fields))
        return definitions

    def _extract_endpoints(self, content: str) -> list[dict]:
        endpoints: list[dict] = []
        for m in self._block_re.finditer(content):
            method = m.group(2)
            start_idx = m.end()
            depth = 1
            i = start_idx
            while i < len(content) and depth > 0:
                if content[i] == "{":
                    depth += 1
                if content[i] == "}":
                    depth -= 1
                i += 1
            block_content = content[start_idx:i - 1]
            block_lines = block_content.split("\n")
            block_start_line = _line_of(content, start_idx)
            for j, bl in enumerate(block_lines):
                fm = self._word_re.match(bl.strip())
                if fm and fm.group(1):
                    line_num = block_start_line + j
                    endpoints.append(_make_endpoint(method, fm.group(1), [line_num, line_num]))
        return endpoints

    def _extract_fields(self, content: str, start_idx: int) -> list[str]:
        fields: list[str] = []
        after = content[start_idx:]
        open_brace = after.find("{")
        if open_brace == -1:
            return fields
        depth = 1
        i = open_brace + 1
        while i < len(after) and depth > 0:
            if after[i] == "{":
                depth += 1
            if after[i] == "}":
                depth -= 1
            i += 1
        body = after[open_brace + 1:i - 1]
        for line in body.split("\n"):
            fm = self._word_re.match(line.strip())
            if fm:
                fields.append(fm.group(1))
        return fields


# ===========================================================================
# Protobuf
# ===========================================================================


class ProtobufParser:
    languages = ["protobuf"]
    _message_re = re.compile(r"^message\s+(\w+)\s*\{", re.MULTILINE)
    _enum_re = re.compile(r"^enum\s+(\w+)\s*\{", re.MULTILINE)
    _service_re = re.compile(r"^service\s+(\w+)\s*\{", re.MULTILINE)
    _rpc_re = re.compile(r"rpc\s+(\w+)\s*\(")
    _field_re = re.compile(
        r"^\s*(?:repeated\s+|optional\s+|required\s+|map<[^>]+>\s+)?\w+\s+(\w+)\s*=", re.MULTILINE
    )
    _value_re = re.compile(r"^\s*(\w+)\s*=", re.MULTILINE)

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(
            definitions=self._extract_definitions(content),
            endpoints=self._extract_service_methods(content),
        )

    def _extract_definitions(self, content: str) -> list[dict]:
        definitions: list[dict] = []
        for m in self._message_re.finditer(content):
            start_line = _line_of(content, m.start())
            fields = self._extract_message_fields(content, m.start())
            after = content[m.start():]
            close_brace = self._find_closing_brace(after)
            end_line = _line_of(content, m.start() + close_brace + 1)
            definitions.append(_make_definition(m.group(1), "message", [start_line, end_line], fields))
        for m in self._enum_re.finditer(content):
            start_line = _line_of(content, m.start())
            fields = self._extract_enum_values(content, m.start())
            after = content[m.start():]
            close_brace = self._find_closing_brace(after)
            end_line = _line_of(content, m.start() + close_brace + 1)
            definitions.append(_make_definition(m.group(1), "enum", [start_line, end_line], fields))
        return definitions

    def _extract_service_methods(self, content: str) -> list[dict]:
        endpoints: list[dict] = []
        for m in self._service_re.finditer(content):
            service_name = m.group(1)
            start_idx = m.end()
            after_service = content[m.start():]
            close_brace = self._find_closing_brace(after_service)
            body = after_service[len(m.group(0)):close_brace]
            for rpc_match in self._rpc_re.finditer(body):
                line_num = _line_of(content, start_idx + rpc_match.start())
                endpoints.append(
                    _make_endpoint("rpc", f"{service_name}.{rpc_match.group(1)}", [line_num, line_num])
                )
        return endpoints

    def _extract_message_fields(self, content: str, start_idx: int) -> list[str]:
        after = content[start_idx:]
        open_brace = after.find("{")
        if open_brace == -1:
            return []
        close_brace = self._find_closing_brace(after)
        body = after[open_brace + 1:close_brace]
        return [m.group(1) for m in self._field_re.finditer(body)]

    def _extract_enum_values(self, content: str, start_idx: int) -> list[str]:
        after = content[start_idx:]
        open_brace = after.find("{")
        if open_brace == -1:
            return []
        close_brace = self._find_closing_brace(after)
        body = after[open_brace + 1:close_brace]
        return [m.group(1) for m in self._value_re.finditer(body)]

    def _find_closing_brace(self, content: str) -> int:
        depth = 0
        for i, ch in enumerate(content):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        return len(content)


# ===========================================================================
# Terraform
# ===========================================================================


class TerraformParser:
    languages = ["terraform"]
    _resource_re = re.compile(r'^resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', re.MULTILINE)
    _data_re = re.compile(r'^data\s+"([^"]+)"\s+"([^"]+)"\s*\{', re.MULTILINE)
    _module_re = re.compile(r'^module\s+"([^"]+)"\s*\{', re.MULTILINE)
    _var_re = re.compile(r'^variable\s+"([^"]+)"\s*\{', re.MULTILINE)
    _output_re = re.compile(r'^output\s+"([^"]+)"\s*\{', re.MULTILINE)

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(
            resources=self._extract_resources(content),
            definitions=self._extract_variables_and_outputs(content),
        )

    def _end_line(self, content: str, start: int) -> int:
        after = content[start:]
        close_brace = self._find_closing_brace(after)
        return _line_of(content, start + close_brace + 1)

    def _extract_resources(self, content: str) -> list[dict]:
        resources: list[dict] = []
        for m in self._resource_re.finditer(content):
            sl = _line_of(content, m.start())
            resources.append(
                _make_resource(f"{m.group(1)}.{m.group(2)}", m.group(1), [sl, self._end_line(content, m.start())])
            )
        for m in self._data_re.finditer(content):
            sl = _line_of(content, m.start())
            resources.append(
                _make_resource(
                    f"data.{m.group(1)}.{m.group(2)}", f"data.{m.group(1)}", [sl, self._end_line(content, m.start())]
                )
            )
        for m in self._module_re.finditer(content):
            sl = _line_of(content, m.start())
            resources.append(
                _make_resource(f"module.{m.group(1)}", "module", [sl, self._end_line(content, m.start())])
            )
        return resources

    def _extract_variables_and_outputs(self, content: str) -> list[dict]:
        definitions: list[dict] = []
        for m in self._var_re.finditer(content):
            sl = _line_of(content, m.start())
            definitions.append(_make_definition(m.group(1), "variable", [sl, self._end_line(content, m.start())], []))
        for m in self._output_re.finditer(content):
            sl = _line_of(content, m.start())
            definitions.append(_make_definition(m.group(1), "output", [sl, self._end_line(content, m.start())], []))
        return definitions

    def _find_closing_brace(self, content: str) -> int:
        depth = 0
        for i, ch in enumerate(content):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        return len(content)


# ===========================================================================
# Makefile
# ===========================================================================


class MakefileParser:
    languages = ["makefile"]
    _target_re = re.compile(r"^([a-zA-Z_.][a-zA-Z0-9_.-]*)(?:\s+.*)?:")

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(steps=self._extract_targets(content))

    def _extract_targets(self, content: str) -> list[dict]:
        targets: list[dict] = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            m = self._target_re.match(line)
            if m and ":=" not in line and "?=" not in line:
                name = m.group(1)
                if name.startswith("."):
                    continue
                end_line = i + 1
                while end_line < len(lines):
                    next_line = lines[end_line]
                    if next_line == "" or next_line.startswith("\t") or next_line.startswith("  "):
                        end_line += 1
                    else:
                        break
                targets.append(_make_step(name, [i + 1, end_line]))
        return targets


# ===========================================================================
# Shell
# ===========================================================================


class ShellParser:
    languages = ["shell", "jenkinsfile"]
    _fn_paren_re = re.compile(r"^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?")
    _fn_kw_re = re.compile(r"^function\s+(\w+)\s*\{?")

    def analyze_file(self, content: str) -> StructuralAnalysis:
        return StructuralAnalysis(functions=self._extract_functions(content))

    def _extract_functions(self, content: str) -> list[dict]:
        functions: list[dict] = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            m = self._fn_paren_re.match(line) or self._fn_kw_re.match(line)
            if not m:
                continue
            name = m.group(1)
            has_brace_here = "{" in line
            next_non_blank = i + 1
            while next_non_blank < len(lines) and lines[next_non_blank].strip() == "":
                next_non_blank += 1
            has_brace_next = next_non_blank < len(lines) and lines[next_non_blank].strip().startswith("{")
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


# ---------------------------------------------------------------------------
# Parser registry (language id -> parser instance)
# ---------------------------------------------------------------------------

_BUILTIN_PARSERS = [
    MarkdownParser(),
    YAMLConfigParser(),
    JSONConfigParser(),
    TOMLParser(),
    EnvParser(),
    DockerfileParser(),
    SQLParser(),
    GraphQLParser(),
    ProtobufParser(),
    TerraformParser(),
    MakefileParser(),
    ShellParser(),
]

PARSERS_BY_ID: dict[str, object] = {}
for _p in _BUILTIN_PARSERS:
    for _lang in _p.languages:  # type: ignore[attr-defined]
        PARSERS_BY_ID[_lang] = _p


def get_parser_for_language(language_id: str):
    return PARSERS_BY_ID.get(language_id)
