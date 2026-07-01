"""Go tree-sitter extractor.

Port of ``plugins/extractors/go-extractor.ts`` adapted to the Python
``tree_sitter`` API.
"""

from __future__ import annotations

import re
from typing import Any

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    node_text,
)

_QUOTE_EDGES_RE = re.compile(r'^"|"$')


def _extract_params(params_node: Any | None) -> list[str]:
    """Extract parameter names from a Go ``parameter_list`` node."""
    if not params_node:
        return []
    params: list[str] = []

    declarations = find_children(params_node, "parameter_declaration")
    for decl in declarations:
        # A parameter_declaration can have multiple name identifiers sharing
        # a type, e.g. `a, b int`. Collect all identifiers.
        for child in decl.children:
            if child is not None and child.type == "identifier":
                params.append(node_text(child))

    return params


def _extract_result_type(node: Any) -> str | None:
    """Extract the return type text from a function/method declaration's result."""
    result = node.child_by_field_name("result")
    if result is None:
        return None
    return node_text(result)


def _extract_receiver_type(receiver_node: Any) -> str | None:
    """Extract the receiver type name from a method_declaration receiver list."""
    decl = find_child(receiver_node, "parameter_declaration")
    if decl is None:
        return None

    # Look for type_identifier directly or inside pointer_type
    for child in decl.children:
        if child is None:
            continue
        if child.type == "type_identifier":
            return node_text(child)
        if child.type == "pointer_type":
            type_id = find_child(child, "type_identifier")
            if type_id is not None:
                return node_text(type_id)
    return None


def _is_exported(name: str) -> bool:
    """Check if a name is exported in Go (starts with an uppercase letter)."""
    if len(name) == 0:
        return False
    first = ord(name[0])
    return 65 <= first <= 90  # A-Z


class GoExtractor:
    """Go extractor for tree-sitter structural analysis and call graph extraction.

    Go-specific mapping decisions:
    - Structs and interfaces are mapped to the ``classes`` array.
    - Methods (with receivers) are stored as functions and also listed in the
      corresponding struct's ``methods`` array.
    - Exports are determined by Go's capitalization convention.
    """

    language_ids: list[str] = ["go"]

    def extract_structure(self, root_node: Any) -> dict[str, Any]:
        functions: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        imports: list[dict[str, Any]] = []
        exports: list[dict[str, Any]] = []

        # Track methods per receiver type so we can attach them to structs
        methods_by_receiver: dict[str, list[str]] = {}

        for node in root_node.children:
            if node is None:
                continue

            if node.type == "function_declaration":
                self._extract_function(node, functions, exports)
            elif node.type == "method_declaration":
                self._extract_method(node, functions, exports, methods_by_receiver)
            elif node.type == "type_declaration":
                self._extract_type_declaration(node, classes, exports)
            elif node.type == "import_declaration":
                self._extract_import_declaration(node, imports)

        # Attach collected methods to their receiver structs/interfaces
        for cls in classes:
            methods = methods_by_receiver.get(cls["name"])
            if methods:
                cls["methods"].extend(methods)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    def extract_call_graph(self, root_node: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        function_stack: list[str] = []

        def walk_for_calls(node: Any) -> None:
            pushed_name = False

            # Track entering function/method declarations
            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    function_stack.append(node_text(name_node))
                    pushed_name = True
            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    function_stack.append(node_text(name_node))
                    pushed_name = True

            # Extract call expressions
            if node.type == "call_expression":
                callee_node = node.child_by_field_name("function")
                if callee_node is not None and len(function_stack) > 0:
                    entries.append(
                        {
                            "caller": function_stack[-1],
                            "callee": node_text(callee_node),
                            "lineNumber": node.start_point[0] + 1,
                        }
                    )

            for child in node.children:
                if child is not None:
                    walk_for_calls(child)

            if pushed_name:
                function_stack.pop()

        walk_for_calls(root_node)

        return entries

    # ---- Private helpers ----

    def _extract_function(
        self,
        node: Any,
        functions: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node)
        return_type = _extract_result_type(node)

        functions.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "params": params,
                "returnType": return_type,
            }
        )

        if _is_exported(node_text(name_node)):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_method(
        self,
        node: Any,
        functions: list[dict[str, Any]],
        exports: list[dict[str, Any]],
        methods_by_receiver: dict[str, list[str]],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node)
        return_type = _extract_result_type(node)

        functions.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "params": params,
                "returnType": return_type,
            }
        )

        # Track receiver type for struct association
        receiver_node = node.child_by_field_name("receiver")
        if receiver_node is not None:
            receiver_type = _extract_receiver_type(receiver_node)
            if receiver_type:
                if receiver_type not in methods_by_receiver:
                    methods_by_receiver[receiver_type] = []
                methods_by_receiver[receiver_type].append(node_text(name_node))

        if _is_exported(node_text(name_node)):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_type_declaration(
        self,
        node: Any,
        classes: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        type_spec = find_child(node, "type_spec")
        if type_spec is None:
            return

        name_node = type_spec.child_by_field_name("name")
        type_node = type_spec.child_by_field_name("type")
        if name_node is None or type_node is None:
            return

        if type_node.type == "struct_type":
            self._extract_struct(node, name_node, type_node, classes, exports)
        elif type_node.type == "interface_type":
            self._extract_interface(node, name_node, type_node, classes, exports)

    def _extract_struct(
        self,
        decl_node: Any,
        name_node: Any,
        struct_node: Any,
        classes: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        properties: list[str] = []

        field_list = find_child(struct_node, "field_declaration_list")
        if field_list is not None:
            fields = find_children(field_list, "field_declaration")
            for field in fields:
                # A field_declaration can have multiple names: `X, Y int`
                for child in field.children:
                    if child is not None and child.type == "field_identifier":
                        properties.append(node_text(child))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [
                    decl_node.start_point[0] + 1,
                    decl_node.end_point[0] + 1,
                ],
                "methods": [],  # Methods are attached later from methods_by_receiver
                "properties": properties,
            }
        )

        if _is_exported(node_text(name_node)):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": decl_node.start_point[0] + 1,
                }
            )

    def _extract_interface(
        self,
        decl_node: Any,
        name_node: Any,
        interface_node: Any,
        classes: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        methods: list[str] = []

        method_elems = find_children(interface_node, "method_elem")
        for elem in method_elems:
            meth_name = elem.child_by_field_name("name")
            if meth_name is not None:
                methods.append(node_text(meth_name))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [
                    decl_node.start_point[0] + 1,
                    decl_node.end_point[0] + 1,
                ],
                "methods": methods,
                "properties": [],  # Interfaces have no properties
            }
        )

        if _is_exported(node_text(name_node)):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": decl_node.start_point[0] + 1,
                }
            )

    def _extract_import_declaration(
        self, node: Any, imports: list[dict[str, Any]]
    ) -> None:
        # Grouped imports: import ( ... )
        spec_list = find_child(node, "import_spec_list")
        if spec_list is not None:
            specs = find_children(spec_list, "import_spec")
            for spec in specs:
                self._extract_import_spec(spec, imports)
        else:
            # Single import: import "fmt"
            spec = find_child(node, "import_spec")
            if spec is not None:
                self._extract_import_spec(spec, imports)

    def _extract_import_spec(
        self, spec: Any, imports: list[dict[str, Any]]
    ) -> None:
        path_node = spec.child_by_field_name("path")
        if path_node is None:
            return

        # Extract unquoted path
        path_content = find_child(path_node, "interpreted_string_literal_content")
        if path_content is not None:
            source = node_text(path_content)
        else:
            source = _QUOTE_EDGES_RE.sub("", node_text(path_node))

        # Determine the specifier: alias if present, otherwise last path component
        name_node = spec.child_by_field_name("name")
        if name_node is not None:
            specifier = node_text(name_node)
        else:
            # Use last path component, e.g. "net/http" -> "http"
            parts = source.split("/")
            specifier = parts[-1]

        imports.append(
            {
                "source": source,
                "specifiers": [specifier],
                "lineNumber": spec.start_point[0] + 1,
            }
        )
