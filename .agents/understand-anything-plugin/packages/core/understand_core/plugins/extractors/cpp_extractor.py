"""C/C++ tree-sitter extractor.

Port of ``plugins/extractors/cpp-extractor.ts`` adapted to the Python
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

_ANGLE_EDGES_RE = re.compile(r"^<|>$")
_QUOTE_EDGES_RE = re.compile(r'^"|"$')


def _unwrap_declarator_name(node: Any) -> str | None:
    """Recursively unwrap nested declarators to find the leaf identifier name.

    C/C++ parameter declarators can be deeply nested (pointer_declarator,
    reference_declarator, array_declarator) wrapping the leaf identifier.
    """
    if node.type == "identifier" or node.type == "field_identifier":
        return node_text(node)
    # Dig into the nested declarator field
    inner = node.child_by_field_name("declarator")
    if inner:
        return _unwrap_declarator_name(inner)
    # Fallback: look for direct identifier/field_identifier child
    id_node = find_child(node, "identifier") or find_child(node, "field_identifier")
    return node_text(id_node) if id_node else None


def _extract_func_decl_name(func_decl: Any) -> dict[str, Any] | None:
    """Extract the function/method name from a ``function_declarator`` node.

    Returns ``{"name", "qualifier"}`` where qualifier is the namespace/class for
    qualified identifiers (e.g. ``Server`` in ``void Server::start()``).
    """
    decl_node = func_decl.child_by_field_name("declarator")
    if not decl_node:
        return None

    if decl_node.type == "identifier" or decl_node.type == "field_identifier":
        return {"name": node_text(decl_node), "qualifier": None}

    if decl_node.type == "qualified_identifier":
        name_node = decl_node.child_by_field_name("name")
        # The qualifier is the namespace_identifier before ::
        ns_node = find_child(decl_node, "namespace_identifier")
        return {
            "name": node_text(name_node) if name_node else node_text(decl_node),
            "qualifier": node_text(ns_node) if ns_node else None,
        }

    return {"name": node_text(decl_node), "qualifier": None}


def _extract_params(params_node: Any | None) -> list[str]:
    """Extract parameter names from a ``parameter_list`` node."""
    if not params_node:
        return []
    params: list[str] = []

    decls = find_children(params_node, "parameter_declaration")
    for decl in decls:
        decl_node = decl.child_by_field_name("declarator")
        if decl_node:
            name = _unwrap_declarator_name(decl_node)
            if name:
                params.append(name)

    return params


def _extract_return_type(node: Any) -> str | None:
    """Extract the return type text from a ``function_definition`` node."""
    type_node = node.child_by_field_name("type")
    if type_node:
        return node_text(type_node)
    return None


def _is_static(node: Any) -> bool:
    """Whether a ``function_definition`` has a ``static`` storage_class_specifier."""
    storage = find_child(node, "storage_class_specifier")
    return storage is not None and node_text(storage) == "static"


class CppExtractor:
    """C/C++ extractor for tree-sitter structural analysis and call graph.

    Handles free functions, classes/structs with members and access specifiers,
    ``#include`` directives, namespaces, out-of-class method definitions, and
    call graph extraction from call_expression nodes. C/C++ has no formal export
    syntax: non-static top-level functions and public members are treated as
    exports.
    """

    language_ids: list[str] = ["cpp", "c"]

    def extract_structure(self, root_node: Any) -> dict[str, Any]:
        """Extract functions, classes, imports, and exports from the AST."""
        functions: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        imports: list[dict[str, Any]] = []
        exports: list[dict[str, Any]] = []

        # Track methods associated with classes via out-of-class definitions
        methods_by_class: dict[str, list[str]] = {}

        self._walk_top_level(
            root_node, functions, classes, imports, exports, methods_by_class
        )

        # Attach out-of-class methods to their corresponding classes
        for cls in classes:
            methods = methods_by_class.get(cls["name"])
            if methods:
                for m in methods:
                    if m not in cls["methods"]:
                        cls["methods"].append(m)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    def extract_call_graph(self, root_node: Any) -> list[dict[str, Any]]:
        """Extract caller/callee edges from call_expression nodes."""
        entries: list[dict[str, Any]] = []
        function_stack: list[str] = []

        def walk_for_calls(node: Any) -> None:
            pushed_name = False

            # Track entering function_definition
            if node.type == "function_definition":
                name = self._extract_function_name(node)
                if name:
                    function_stack.append(name)
                    pushed_name = True

            # Extract call_expression nodes
            if node.type == "call_expression":
                if len(function_stack) > 0:
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
                if child is not None:
                    walk_for_calls(child)

            if pushed_name:
                function_stack.pop()

        walk_for_calls(root_node)

        return entries

    # ---- Private helpers ----

    def _walk_top_level(
        self,
        parent_node: Any,
        functions: list[dict[str, Any]],
        classes: list[dict[str, Any]],
        imports: list[dict[str, Any]],
        exports: list[dict[str, Any]],
        methods_by_class: dict[str, list[str]],
    ) -> None:
        """Walk top-level declarations, recursing into namespace bodies."""
        for node in parent_node.children:
            if not node:
                continue

            node_type = node.type
            if node_type == "preproc_include":
                self._extract_include(node, imports)
            elif node_type == "class_specifier":
                self._extract_class_or_struct(
                    node, "class", classes, functions, exports
                )
            elif node_type == "struct_specifier":
                self._extract_class_or_struct(
                    node, "struct", classes, functions, exports
                )
            elif node_type == "function_definition":
                self._extract_function_def(node, functions, exports, methods_by_class)
            elif node_type == "namespace_definition":
                # Recurse into namespace body (declaration_list)
                body = find_child(node, "declaration_list")
                if body:
                    self._walk_top_level(
                        body, functions, classes, imports, exports, methods_by_class
                    )
            elif node_type == "declaration":
                # A top-level ";" terminated statement could wrap a class/struct
                # specifier (e.g. `class Foo { ... };`). Check for nested ones.
                inner_class = find_child(node, "class_specifier")
                if inner_class:
                    self._extract_class_or_struct(
                        inner_class, "class", classes, functions, exports
                    )
                inner_struct = find_child(node, "struct_specifier")
                if inner_struct:
                    self._extract_class_or_struct(
                        inner_struct, "struct", classes, functions, exports
                    )

    def _extract_function_name(self, node: Any) -> str | None:
        """Extract the simple function name from a ``function_definition``."""
        decl_node = node.child_by_field_name("declarator")
        if not decl_node or decl_node.type != "function_declarator":
            return None

        info = _extract_func_decl_name(decl_node)
        return info["name"] if info else None

    def _extract_include(self, node: Any, imports: list[dict[str, Any]]) -> None:
        """Extract a ``#include`` directive into the imports array."""
        path_node = node.child_by_field_name("path")
        if not path_node:
            return

        if path_node.type == "system_lib_string":
            # Strip angle brackets: <iostream> -> iostream
            source = _ANGLE_EDGES_RE.sub("", node_text(path_node))
        elif path_node.type == "string_literal":
            # Extract content from string: "myfile.h" -> myfile.h
            content = find_child(path_node, "string_content")
            source = (
                node_text(content)
                if content
                else _QUOTE_EDGES_RE.sub("", node_text(path_node))
            )
        else:
            source = node_text(path_node)

        imports.append(
            {
                "source": source,
                "specifiers": [source],
                "lineNumber": node.start_point[0] + 1,
            }
        )

    def _extract_class_or_struct(
        self,
        node: Any,
        kind: str,
        classes: list[dict[str, Any]],
        functions: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        """Extract a ``class_specifier`` or ``struct_specifier`` into classes.

        Public members of classes and all members of structs (default public)
        are treated as exports.
        """
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        class_name = node_text(name_node)
        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body and body.type == "field_declaration_list":
            # Default access: public for struct, private for class
            current_access = "public" if kind == "struct" else "private"

            for member in body.children:
                if not member:
                    continue

                if member.type == "access_specifier":
                    # Update current access level
                    spec_child = member.children[0] if member.children else None
                    if spec_child:
                        current_access = node_text(spec_child)
                    continue

                if member.type == "field_declaration":
                    decl_node = member.child_by_field_name("declarator")
                    if decl_node and decl_node.type == "function_declarator":
                        # Method declaration (no body)
                        info = _extract_func_decl_name(decl_node)
                        if info:
                            methods.append(info["name"])
                            if current_access == "public":
                                exports.append(
                                    {
                                        "name": info["name"],
                                        "lineNumber": member.start_point[0] + 1,
                                    }
                                )
                    elif decl_node:
                        # Property (field_identifier or other declarator)
                        name = _unwrap_declarator_name(decl_node)
                        if name:
                            properties.append(name)

                if member.type == "function_definition":
                    # Inline method definition
                    func_decl = member.child_by_field_name("declarator")
                    if func_decl and func_decl.type == "function_declarator":
                        info = _extract_func_decl_name(func_decl)
                        if info:
                            methods.append(info["name"])

                            # Also add to functions list with params/return type
                            params_node = func_decl.child_by_field_name("parameters")
                            functions.append(
                                {
                                    "name": info["name"],
                                    "lineRange": [
                                        member.start_point[0] + 1,
                                        member.end_point[0] + 1,
                                    ],
                                    "params": _extract_params(params_node),
                                    "returnType": _extract_return_type(member),
                                }
                            )

                            if current_access == "public":
                                exports.append(
                                    {
                                        "name": info["name"],
                                        "lineNumber": member.start_point[0] + 1,
                                    }
                                )

        classes.append(
            {
                "name": class_name,
                "lineRange": [
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                ],
                "methods": methods,
                "properties": properties,
            }
        )

        # The class/struct name itself is an export (non-anonymous types are
        # always exported in C/C++ headers).
        exports.append(
            {
                "name": class_name,
                "lineNumber": node.start_point[0] + 1,
            }
        )

    def _extract_function_def(
        self,
        node: Any,
        functions: list[dict[str, Any]],
        exports: list[dict[str, Any]],
        methods_by_class: dict[str, list[str]],
    ) -> None:
        """Extract a free function or out-of-class method definition.

        Out-of-class definitions (e.g. ``void Server::start()``) are tracked in
        ``methods_by_class``. Static functions are NOT exported.
        """
        func_decl = node.child_by_field_name("declarator")
        if not func_decl or func_decl.type != "function_declarator":
            return

        info = _extract_func_decl_name(func_decl)
        if not info:
            return

        params_node = func_decl.child_by_field_name("parameters")
        params = _extract_params(params_node)
        return_type = _extract_return_type(node)

        functions.append(
            {
                "name": info["name"],
                "lineRange": [
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                ],
                "params": params,
                "returnType": return_type,
            }
        )

        # Track out-of-class method definitions (e.g. void Server::start())
        if info["qualifier"]:
            if info["qualifier"] not in methods_by_class:
                methods_by_class[info["qualifier"]] = []
            methods_by_class[info["qualifier"]].append(info["name"])

        # Non-static top-level functions are exports
        if not _is_static(node):
            exports.append(
                {
                    "name": info["name"],
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_callee_name(self, call_node: Any) -> str | None:
        """Extract the callee name from a ``call_expression``."""
        func_node = call_node.children[0] if call_node.children else None
        if not func_node:
            return None

        if func_node.type == "identifier":
            return node_text(func_node)

        if func_node.type == "field_expression":
            field = func_node.child_by_field_name("field")
            return node_text(field) if field else node_text(func_node)

        if func_node.type == "qualified_identifier":
            return node_text(func_node)

        return node_text(func_node)
