"""C# language extractor for tree-sitter structural / call-graph analysis.

Port of ``plugins/extractors/csharp-extractor.ts``.
"""

from __future__ import annotations

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    node_text,
)
from understand_core.plugins.extractors.types import TreeSitterNode


def _extract_params(params_node: TreeSitterNode | None) -> list[str]:
    """Parameter names from a C# ``parameter_list`` node."""
    if not params_node:
        return []
    params: list[str] = []

    param_nodes = find_children(params_node, "parameter")
    for param in param_nodes:
        name_node = param.child_by_field_name("name")
        if name_node:
            params.append(node_text(name_node))

    return params


def _extract_return_type(node: TreeSitterNode) -> str | None:
    """Return type text from a ``method_declaration`` via the ``returns`` field."""
    type_node = node.child_by_field_name("returns")
    if not type_node:
        return None
    return node_text(type_node)


def _has_modifier(node: TreeSitterNode, modifier: str) -> bool:
    """Whether ``node`` has a separate ``modifier`` child containing ``modifier``."""
    modifier_nodes = find_children(node, "modifier")
    for mod in modifier_nodes:
        for child in mod.children:
            if child and node_text(child) == modifier:
                return True
    return False


def _extract_using_source(node: TreeSitterNode) -> str | None:
    """Namespace source text from a ``using_directive`` (handles aliases)."""
    has_equals = find_child(node, "=") is not None

    if has_equals:
        qualified_name = find_child(node, "qualified_name")
        return node_text(qualified_name) if qualified_name else None

    qualified_name = find_child(node, "qualified_name")
    if qualified_name:
        return node_text(qualified_name)

    identifier = find_child(node, "identifier")
    return node_text(identifier) if identifier else None


def _last_component(path: str) -> str:
    """Last component of a dotted namespace path."""
    parts = path.split(".")
    return parts[-1]


def _extract_invocation_name(node: TreeSitterNode) -> str | None:
    """Callee name from an ``invocation_expression`` node."""
    func_node = node.child_by_field_name("function")
    if not func_node:
        return None
    return node_text(func_node)


class CSharpExtractor:
    """C# extractor for tree-sitter structural analysis and call-graph extraction."""

    language_ids: list[str] = ["csharp"]

    def extract_structure(self, root_node: TreeSitterNode) -> dict:
        """Extract functions, classes, imports, and exports from a C# file."""
        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        exports: list[dict] = []

        self._walk_top_level(root_node, functions, classes, imports, exports)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    def extract_call_graph(self, root_node: TreeSitterNode) -> list[dict]:
        """Extract caller/callee relationships from a C# file."""
        entries: list[dict] = []
        function_stack: list[str] = []

        def walk_for_calls(node: TreeSitterNode) -> None:
            pushed_name = False

            if node.type in ("method_declaration", "constructor_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    function_stack.append(node_text(name_node))
                    pushed_name = True

            if node.type == "invocation_expression":
                if len(function_stack) > 0:
                    callee = _extract_invocation_name(node)
                    if callee:
                        entries.append({
                            "caller": function_stack[-1],
                            "callee": callee,
                            "lineNumber": node.start_point[0] + 1,
                        })

            if node.type == "object_creation_expression":
                if len(function_stack) > 0:
                    type_node = find_child(node, "identifier") or find_child(node, "generic_name")
                    if type_node:
                        entries.append({
                            "caller": function_stack[-1],
                            "callee": "new " + node_text(type_node),
                            "lineNumber": node.start_point[0] + 1,
                        })

            for child in node.children:
                if child:
                    walk_for_calls(child)

            if pushed_name:
                function_stack.pop()

        walk_for_calls(root_node)

        return entries

    # ---- Private helpers ----

    def _walk_top_level(
        self,
        node: TreeSitterNode,
        functions: list[dict],
        classes: list[dict],
        imports: list[dict],
        exports: list[dict],
    ) -> None:
        """Walk top-level nodes, recursing into namespace bodies."""
        for child in node.children:
            if not child:
                continue

            if child.type == "using_directive":
                self._extract_using(child, imports)
            elif child.type == "namespace_declaration":
                self._walk_namespace_body(child, functions, classes, imports, exports)
            elif child.type == "file_scoped_namespace_declaration":
                # File-scoped namespace: declarations are siblings at the root.
                pass
            elif child.type == "class_declaration":
                self._extract_class(child, functions, classes, exports)
            elif child.type == "interface_declaration":
                self._extract_interface(child, functions, classes, exports)

    def _walk_namespace_body(
        self,
        ns_node: TreeSitterNode,
        functions: list[dict],
        classes: list[dict],
        imports: list[dict],
        exports: list[dict],
    ) -> None:
        """Walk into a ``namespace_declaration``'s body to find declarations."""
        body = ns_node.child_by_field_name("body")
        if not body:
            return

        for child in body.children:
            if not child:
                continue

            if child.type == "class_declaration":
                self._extract_class(child, functions, classes, exports)
            elif child.type == "interface_declaration":
                self._extract_interface(child, functions, classes, exports)
            elif child.type == "namespace_declaration":
                self._walk_namespace_body(child, functions, classes, imports, exports)

    def _extract_using(self, node: TreeSitterNode, imports: list[dict]) -> None:
        """Map a ``using_directive`` to an import."""
        source = _extract_using_source(node)
        if not source:
            return

        imports.append({
            "source": source,
            "specifiers": [_last_component(source)],
            "lineNumber": node.start_point[0] + 1,
        })

    def _extract_class(
        self,
        node: TreeSitterNode,
        functions: list[dict],
        classes: list[dict],
        exports: list[dict],
    ) -> None:
        """Extract a ``class_declaration`` into classes/functions/exports."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            self._extract_class_body_members(body, methods, properties, functions, exports)

        classes.append({
            "name": node_text(name_node),
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "methods": methods,
            "properties": properties,
        })

        if _has_modifier(node, "public"):
            exports.append({
                "name": node_text(name_node),
                "lineNumber": node.start_point[0] + 1,
            })

    def _extract_interface(
        self,
        node: TreeSitterNode,
        functions: list[dict],
        classes: list[dict],
        exports: list[dict],
    ) -> None:
        """Extract an ``interface_declaration`` into classes/exports."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            method_nodes = find_children(body, "method_declaration")
            for method_node in method_nodes:
                meth_name_node = method_node.child_by_field_name("name")
                if meth_name_node:
                    methods.append(node_text(meth_name_node))

            prop_nodes = find_children(body, "property_declaration")
            for prop_node in prop_nodes:
                prop_name_node = prop_node.child_by_field_name("name")
                if prop_name_node:
                    properties.append(node_text(prop_name_node))

        classes.append({
            "name": node_text(name_node),
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "methods": methods,
            "properties": properties,
        })

        if _has_modifier(node, "public"):
            exports.append({
                "name": node_text(name_node),
                "lineNumber": node.start_point[0] + 1,
            })

    def _extract_class_body_members(
        self,
        body: TreeSitterNode,
        methods: list[str],
        properties: list[str],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        """Extract methods, constructors, properties, and fields from a class body."""
        for child in body.children:
            if not child:
                continue

            if child.type == "method_declaration":
                self._extract_method(child, methods, functions, exports)
            elif child.type == "constructor_declaration":
                self._extract_constructor(child, methods, functions, exports)
            elif child.type == "property_declaration":
                self._extract_property(child, properties, exports)
            elif child.type == "field_declaration":
                self._extract_field(child, properties, exports)

    def _extract_method(
        self,
        node: TreeSitterNode,
        methods: list[str],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        """Extract a ``method_declaration``."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node or None)
        return_type = _extract_return_type(node)

        methods.append(node_text(name_node))

        functions.append({
            "name": node_text(name_node),
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "params": params,
            "returnType": return_type,
        })

        if _has_modifier(node, "public"):
            exports.append({
                "name": node_text(name_node),
                "lineNumber": node.start_point[0] + 1,
            })

    def _extract_constructor(
        self,
        node: TreeSitterNode,
        methods: list[str],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        """Extract a ``constructor_declaration`` (no return type)."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node or None)

        methods.append(node_text(name_node))

        functions.append({
            "name": node_text(name_node),
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "params": params,
            "returnType": None,
        })

        if _has_modifier(node, "public"):
            exports.append({
                "name": node_text(name_node),
                "lineNumber": node.start_point[0] + 1,
            })

    def _extract_property(
        self,
        node: TreeSitterNode,
        properties: list[str],
        exports: list[dict],
    ) -> None:
        """Extract a ``property_declaration``."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        properties.append(node_text(name_node))

        if _has_modifier(node, "public"):
            exports.append({
                "name": node_text(name_node),
                "lineNumber": node.start_point[0] + 1,
            })

    def _extract_field(
        self,
        node: TreeSitterNode,
        properties: list[str],
        exports: list[dict],
    ) -> None:
        """Extract a ``field_declaration`` (may declare multiple variables)."""
        var_decl = find_child(node, "variable_declaration")
        if not var_decl:
            return

        declarators = find_children(var_decl, "variable_declarator")
        for decl in declarators:
            name_node = find_child(decl, "identifier")
            if name_node:
                properties.append(node_text(name_node))

                if _has_modifier(node, "public"):
                    exports.append({
                        "name": node_text(name_node),
                        "lineNumber": node.start_point[0] + 1,
                    })
