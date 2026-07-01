"""PHP language extractor for tree-sitter structural / call-graph analysis.

Port of ``plugins/extractors/php-extractor.ts``.
"""

from __future__ import annotations

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    node_text,
)
from understand_core.plugins.extractors.types import TreeSitterNode


def _extract_params(params_node: TreeSitterNode | None) -> list[str]:
    """Parameter names from a PHP ``formal_parameters`` node (incl. ``$``)."""
    if not params_node:
        return []
    params: list[str] = []

    simple_params = find_children(params_node, "simple_parameter")
    for param in simple_params:
        var_name = find_child(param, "variable_name")
        if var_name:
            params.append(node_text(var_name))

    return params


def _extract_return_type(node: TreeSitterNode) -> str | None:
    """Return type string from siblings following ``formal_parameters``."""
    found_colon = False
    for child in node.children:
        if not child:
            continue

        if child.type == ":" and node_text(child) == ":":
            found_colon = True
            continue

        if found_colon:
            if child.type in (
                "primitive_type",
                "named_type",
                "optional_type",
                "union_type",
            ):
                return node_text(child)

    return None


def _extract_use_name(clause: TreeSitterNode, prefix: str) -> str:
    """Reconstruct a fully-qualified name from a ``namespace_use_clause``."""
    qualified_name = find_child(clause, "qualified_name")
    if qualified_name:
        return node_text(qualified_name)
    # Inside a grouped use, the clause may just be a `name` node
    name_node = find_child(clause, "name")
    if name_node and prefix:
        return prefix + "\\" + node_text(name_node)
    if name_node:
        return node_text(name_node)
    return node_text(clause)


def _last_segment(fqn: str) -> str:
    """Last segment (class/interface name) of a fully-qualified name."""
    parts = fqn.split("\\")
    return parts[-1]


class PhpExtractor:
    """PHP extractor for tree-sitter structural analysis and call-graph extraction."""

    language_ids: list[str] = ["php"]

    def extract_structure(self, root_node: TreeSitterNode) -> dict:
        """Extract functions, classes, imports, and exports from a PHP file."""
        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        exports: list[dict] = []

        self._walk_statements(root_node, functions, classes, imports, exports)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    def _walk_statements(
        self,
        parent: TreeSitterNode,
        functions: list[dict],
        classes: list[dict],
        imports: list[dict],
        exports: list[dict],
    ) -> None:
        """Walk top-level statements (recursing into block-scoped namespaces)."""
        for node in parent.children:
            if not node:
                continue

            if node.type == "function_definition":
                self._extract_function(node, functions)
                exports.append({
                    "name": self._get_function_name(node),
                    "lineNumber": node.start_point[0] + 1,
                })
            elif node.type == "class_declaration":
                self._extract_class(node, classes, functions)
                exports.append({
                    "name": self._get_class_name(node),
                    "lineNumber": node.start_point[0] + 1,
                })
            elif node.type == "interface_declaration":
                self._extract_interface(node, classes)
                exports.append({
                    "name": self._get_interface_name(node),
                    "lineNumber": node.start_point[0] + 1,
                })
            elif node.type == "namespace_use_declaration":
                self._extract_use_declaration(node, imports)
            elif node.type == "namespace_definition":
                body = find_child(node, "compound_statement")
                if body:
                    self._walk_statements(body, functions, classes, imports, exports)

    def extract_call_graph(self, root_node: TreeSitterNode) -> list[dict]:
        """Extract caller/callee relationships from a PHP file."""
        entries: list[dict] = []
        function_stack: list[str] = []

        def walk_for_calls(node: TreeSitterNode) -> None:
            pushed_name = False

            if node.type in ("function_definition", "method_declaration"):
                name_node = find_child(node, "name")
                if name_node:
                    function_stack.append(node_text(name_node))
                    pushed_name = True

            if len(function_stack) > 0:
                caller = function_stack[-1]

                if node.type == "function_call_expression":
                    name_node = find_child(node, "name")
                    if name_node:
                        entries.append({
                            "caller": caller,
                            "callee": node_text(name_node),
                            "lineNumber": node.start_point[0] + 1,
                        })
                elif node.type == "member_call_expression":
                    name_node = find_child(node, "name")
                    if name_node:
                        first_child = node.children[0] if node.children else None
                        receiver = node_text(first_child) if first_child else ""
                        callee = (
                            receiver + "->" + node_text(name_node)
                            if receiver
                            else node_text(name_node)
                        )
                        entries.append({
                            "caller": caller,
                            "callee": callee,
                            "lineNumber": node.start_point[0] + 1,
                        })
                elif node.type == "scoped_call_expression":
                    scope_node = node.children[0] if len(node.children) > 0 else None
                    method_node = node.children[2] if len(node.children) > 2 else None
                    if scope_node and method_node and method_node.type == "name":
                        entries.append({
                            "caller": caller,
                            "callee": node_text(scope_node) + "::" + node_text(method_node),
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

    def _get_function_name(self, node: TreeSitterNode) -> str:
        name_node = find_child(node, "name")
        return node_text(name_node) if name_node else ""

    def _get_class_name(self, node: TreeSitterNode) -> str:
        name_node = find_child(node, "name")
        return node_text(name_node) if name_node else ""

    def _get_interface_name(self, node: TreeSitterNode) -> str:
        name_node = find_child(node, "name")
        return node_text(name_node) if name_node else ""

    def _extract_function(self, node: TreeSitterNode, functions: list[dict]) -> None:
        """Extract a ``function_definition``."""
        name_node = find_child(node, "name")
        if not name_node:
            return

        params_node = find_child(node, "formal_parameters")
        params = _extract_params(params_node)
        return_type = _extract_return_type(node)

        functions.append({
            "name": node_text(name_node),
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "params": params,
            "returnType": return_type,
        })

    def _extract_class(
        self,
        node: TreeSitterNode,
        classes: list[dict],
        functions: list[dict],
    ) -> None:
        """Extract a ``class_declaration``."""
        name = self._get_class_name(node)
        if not name:
            return

        methods: list[str] = []
        properties: list[str] = []

        decl_list = find_child(node, "declaration_list")
        if decl_list:
            self._extract_declaration_list(decl_list, methods, properties, functions)

        classes.append({
            "name": name,
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "methods": methods,
            "properties": properties,
        })

    def _extract_interface(self, node: TreeSitterNode, classes: list[dict]) -> None:
        """Extract an ``interface_declaration``."""
        name = self._get_interface_name(node)
        if not name:
            return

        methods: list[str] = []
        properties: list[str] = []

        decl_list = find_child(node, "declaration_list")
        if decl_list:
            method_decls = find_children(decl_list, "method_declaration")
            for method_decl in method_decls:
                method_name = find_child(method_decl, "name")
                if method_name:
                    methods.append(node_text(method_name))

        classes.append({
            "name": name,
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "methods": methods,
            "properties": properties,
        })

    def _extract_declaration_list(
        self,
        decl_list: TreeSitterNode,
        methods: list[str],
        properties: list[str],
        functions: list[dict],
    ) -> None:
        """Extract methods and properties from a class ``declaration_list``."""
        for member in decl_list.children:
            if not member:
                continue

            if member.type == "method_declaration":
                name_node = find_child(member, "name")
                if name_node:
                    methods.append(node_text(name_node))

                    params_node = find_child(member, "formal_parameters")
                    params = _extract_params(params_node)
                    return_type = _extract_return_type(member)

                    functions.append({
                        "name": node_text(name_node),
                        "lineRange": [member.start_point[0] + 1, member.end_point[0] + 1],
                        "params": params,
                        "returnType": return_type,
                    })
            elif member.type == "property_declaration":
                prop_element = find_child(member, "property_element")
                if prop_element:
                    var_name = find_child(prop_element, "variable_name")
                    if var_name:
                        dollar_child = find_child(var_name, "name")
                        if dollar_child:
                            properties.append(node_text(dollar_child))
                        else:
                            properties.append(node_text(var_name).lstrip("$"))

    def _extract_use_declaration(
        self,
        node: TreeSitterNode,
        imports: list[dict],
    ) -> None:
        """Extract imports from a ``namespace_use_declaration`` node."""
        use_group = find_child(node, "namespace_use_group")
        if use_group:
            ns_name = find_child(node, "namespace_name")
            prefix = node_text(ns_name) if ns_name else ""

            clauses = find_children(use_group, "namespace_use_clause")
            specifiers: list[str] = []
            for clause in clauses:
                name = _extract_use_name(clause, prefix)
                specifiers.append(_last_segment(name))

            source = (
                prefix + "\\{" + ", ".join(specifiers) + "}"
                if prefix
                else ", ".join(specifiers)
            )

            imports.append({
                "source": source,
                "specifiers": specifiers,
                "lineNumber": node.start_point[0] + 1,
            })
            return

        clauses = find_children(node, "namespace_use_clause")
        for clause in clauses:
            fqn = _extract_use_name(clause, "")
            specifier = _last_segment(fqn)

            imports.append({
                "source": fqn,
                "specifiers": [specifier],
                "lineNumber": node.start_point[0] + 1,
            })
