"""Kotlin language extractor for tree-sitter structural / call-graph analysis.

Port of ``plugins/extractors/kotlin-extractor.ts``.
"""

from __future__ import annotations

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    node_text,
)
from understand_core.plugins.extractors.types import TreeSitterNode


def _extract_visibility(decl_node: TreeSitterNode) -> str | None:
    """Visibility keyword text from a declaration's ``modifiers`` child, or None."""
    modifiers = find_child(decl_node, "modifiers")
    if not modifiers:
        return None
    visibility = find_child(modifiers, "visibility_modifier")
    if not visibility:
        return None
    return node_text(visibility)


def _is_exported(decl_node: TreeSitterNode) -> bool:
    """Whether a Kotlin declaration is visible to other files (default public)."""
    visibility = _extract_visibility(decl_node)
    return visibility is None or visibility != "private"


def _extract_declaration_name(decl_node: TreeSitterNode) -> str | None:
    """Name of a Kotlin declaration.

    The grammar names functions/objects with a ``simple_identifier`` child and
    classes/interfaces with a ``type_identifier`` child.
    """
    for child in decl_node.children:
        if child and child.type in ("simple_identifier", "type_identifier"):
            return node_text(child)
    return None


def _extract_params(decl_node: TreeSitterNode) -> list[str]:
    """Parameter names from a ``function_value_parameters`` node."""
    params: list[str] = []
    value_params = find_child(decl_node, "function_value_parameters")
    if not value_params:
        return params
    for param in find_children(value_params, "parameter"):
        # The first `simple_identifier` inside a parameter is its name.
        id_ = find_child(param, "simple_identifier")
        if id_:
            params.append(node_text(id_))
    return params


def _extract_return_type(decl_node: TreeSitterNode) -> str | None:
    """Return type text from a ``function_declaration`` after the ``:`` separator."""
    # function_value_parameters comes before the optional `: <type>` block;
    # walk children from after the parameters to find `:` followed by a type.
    saw_params = False
    children = decl_node.children
    for i, child in enumerate(children):
        if child is None:
            continue
        if child.type == "function_value_parameters":
            saw_params = True
            continue
        if saw_params and child.type == ":":
            # The next named sibling is the type
            for j in range(i + 1, len(children)):
                nxt = children[j]
                if nxt and nxt.is_named:
                    return node_text(nxt)
    return None


def _extract_property_name(prop_node: TreeSitterNode) -> str | None:
    """Property name from a ``property_declaration`` via ``variable_declaration``."""
    var_decl = find_child(prop_node, "variable_declaration")
    if not var_decl:
        return None
    id_ = find_child(var_decl, "simple_identifier")
    return node_text(id_) if id_ else None


def _collect_class_body(
    body: TreeSitterNode,
    methods: list[str],
    properties: list[str],
    functions: list[dict],
    exports: list[dict],
) -> None:
    """Walk a ``class_body`` collecting functions + properties."""
    for member in body.children:
        if member is None:
            continue

        if member.type == "function_declaration":
            name = _extract_declaration_name(member)
            if not name:
                continue
            methods.append(name)
            functions.append(
                {
                    "name": name,
                    "lineRange": [member.start_point[0] + 1, member.end_point[0] + 1],
                    "params": _extract_params(member),
                    "returnType": _extract_return_type(member),
                }
            )
            if _is_exported(member):
                exports.append(
                    {"name": name, "lineNumber": member.start_point[0] + 1}
                )
        elif member.type == "property_declaration":
            name = _extract_property_name(member)
            if name:
                properties.append(name)
            if name and _is_exported(member):
                exports.append(
                    {"name": name, "lineNumber": member.start_point[0] + 1}
                )
        elif member.type == "object_declaration":
            # Nested companion-object / object members are surfaced as a single
            # synthetic property pointing at the inner object's name.
            name = _extract_declaration_name(member)
            if name:
                properties.append(name)


def _collect_primary_constructor_properties(
    decl_node: TreeSitterNode,
    properties: list[str],
) -> None:
    """Surface every ``val``/``var`` primary-constructor parameter as a property."""
    primary = find_child(decl_node, "primary_constructor")
    if not primary:
        return
    # In this grammar the `class_parameter` nodes are direct children of the
    # `primary_constructor` (there is no `class_parameters` wrapper).
    for param in find_children(primary, "class_parameter"):
        # A class_parameter that carries a `val`/`var` binding is a property.
        # The keyword lives inside a `binding_pattern_kind` child (and, more
        # defensively, may also appear directly).
        is_property = False
        for child in param.children:
            if child is None:
                continue
            if child.type in ("val", "var"):
                is_property = True
                break
            if child.type == "binding_pattern_kind" and any(
                gc and gc.type in ("val", "var") for gc in child.children
            ):
                is_property = True
                break
        if not is_property:
            continue
        id_ = find_child(param, "simple_identifier")
        if id_:
            properties.append(node_text(id_))


class KotlinExtractor:
    """Kotlin extractor for structural analysis and call graph extraction."""

    language_ids: list[str] = ["kotlin"]

    def extract_structure(self, root_node: TreeSitterNode) -> dict:
        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        exports: list[dict] = []

        for node in root_node.children:
            if node is None:
                continue

            if node.type == "package_header":
                # Package is metadata about this file, not a graph member. Skip.
                pass
            elif node.type == "import_list":
                # Imports are wrapped in an `import_list` of `import_header`s.
                for header in find_children(node, "import_header"):
                    self._extract_import(header, imports)
            elif node.type == "import_header":
                self._extract_import(node, imports)
            elif node.type == "function_declaration":
                self._extract_top_level_function(node, functions, exports)
            elif node.type == "class_declaration":
                self._extract_class_declaration(node, classes, functions, exports)
            elif node.type == "object_declaration":
                self._extract_object_declaration(node, classes, functions, exports)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    def extract_call_graph(self, root_node: TreeSitterNode) -> list[dict]:
        entries: list[dict] = []
        function_stack: list[str] = []

        def walk(node: TreeSitterNode) -> None:
            pushed = False

            if node.type == "function_declaration":
                name = _extract_declaration_name(node)
                if name:
                    function_stack.append(name)
                    pushed = True

            if node.type == "call_expression" and function_stack:
                callee = self._extract_callee_name(node)
                if callee:
                    entries.append(
                        {
                            "caller": function_stack[-1],
                            "callee": callee,
                            "lineNumber": node.start_point[0] + 1,
                        }
                    )

            for child in node.children:
                if child:
                    walk(child)

            if pushed:
                function_stack.pop()

        walk(root_node)
        return entries

    # ---- Private helpers ----

    def _extract_top_level_function(
        self,
        decl_node: TreeSitterNode,
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        name = _extract_declaration_name(decl_node)
        if not name:
            return
        functions.append(
            {
                "name": name,
                "lineRange": [decl_node.start_point[0] + 1, decl_node.end_point[0] + 1],
                "params": _extract_params(decl_node),
                "returnType": _extract_return_type(decl_node),
            }
        )
        if _is_exported(decl_node):
            exports.append(
                {"name": name, "lineNumber": decl_node.start_point[0] + 1}
            )

    def _extract_class_declaration(
        self,
        decl_node: TreeSitterNode,
        classes: list[dict],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        name = _extract_declaration_name(decl_node)
        if not name:
            return

        properties: list[str] = []
        methods: list[str] = []

        # 1. Primary-constructor `val`/`var` parameters become properties.
        _collect_primary_constructor_properties(decl_node, properties)

        # 2. Body members (if any).
        body = find_child(decl_node, "class_body")
        if body:
            _collect_class_body(body, methods, properties, functions, exports)

        classes.append(
            {
                "name": name,
                "lineRange": [decl_node.start_point[0] + 1, decl_node.end_point[0] + 1],
                "methods": methods,
                "properties": properties,
            }
        )

        if _is_exported(decl_node):
            exports.append(
                {"name": name, "lineNumber": decl_node.start_point[0] + 1}
            )

    def _extract_object_declaration(
        self,
        decl_node: TreeSitterNode,
        classes: list[dict],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        name = _extract_declaration_name(decl_node)
        if not name:
            return

        properties: list[str] = []
        methods: list[str] = []

        body = find_child(decl_node, "class_body")
        if body:
            _collect_class_body(body, methods, properties, functions, exports)

        classes.append(
            {
                "name": name,
                "lineRange": [decl_node.start_point[0] + 1, decl_node.end_point[0] + 1],
                "methods": methods,
                "properties": properties,
            }
        )

        if _is_exported(decl_node):
            exports.append(
                {"name": name, "lineNumber": decl_node.start_point[0] + 1}
            )

    def _extract_import(
        self,
        decl_node: TreeSitterNode,
        imports: list[dict],
    ) -> None:
        # The dotted path is a single `identifier` node whose `simple_identifier`
        # children are the path segments.
        qualified = find_child(decl_node, "identifier")
        if not qualified:
            return

        parts: list[str] = []
        for id_ in find_children(qualified, "simple_identifier"):
            parts.append(node_text(id_))
        if len(parts) == 0:
            return

        source = ".".join(parts)

        # A wildcard import has a sibling `wildcard_import` ("*"); an aliased
        # import has an `import_alias` -> `type_identifier` sibling.
        specifier = parts[-1]
        for child in decl_node.children:
            if child is None:
                continue
            if child.type == "wildcard_import":
                specifier = "*"
            elif child.type == "import_alias":
                alias = find_child(child, "type_identifier")
                if alias:
                    specifier = node_text(alias)

        imports.append(
            {
                "source": source,
                "specifiers": [specifier],
                "lineNumber": decl_node.start_point[0] + 1,
            }
        )

    def _extract_callee_name(self, call_node: TreeSitterNode) -> str | None:
        """Callee name from a Kotlin ``call_expression``."""
        first = call_node.children[0] if call_node.children else None
        if not first:
            return None

        if first.type == "simple_identifier":
            return node_text(first)

        if first.type == "navigation_expression":
            # The method name lives in the trailing `navigation_suffix` ->
            # `simple_identifier`; fall back to the last `simple_identifier`.
            suffix = None
            for child in first.children:
                if child and child.type == "navigation_suffix":
                    suffix = child
            if suffix:
                id_ = find_child(suffix, "simple_identifier")
                if id_:
                    return node_text(id_)
            last_identifier: str | None = None
            for child in first.children:
                if child and child.type == "simple_identifier":
                    last_identifier = node_text(child)
            return last_identifier
        return None
