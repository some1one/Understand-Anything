"""Python tree-sitter extractor.

Port of ``plugins/extractors/python-extractor.ts`` adapted to the Python
``tree_sitter`` API.
"""

from __future__ import annotations

from typing import Any

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    node_text,
)


def _extract_params(params_node: Any | None) -> list[str]:
    """Extract parameter names from a Python ``parameters`` node.

    Handles identifier, typed_parameter, default_parameter,
    typed_default_parameter, list_splat_pattern (*args),
    dictionary_splat_pattern (**kwargs).
    """
    if not params_node:
        return []
    params: list[str] = []

    for child in params_node.children:
        if child is None:
            continue

        if child.type == "identifier":
            # Skip `self` and `cls` — they are implicit, not real parameters
            text = node_text(child)
            if text != "self" and text != "cls":
                params.append(text)
        elif child.type == "typed_parameter":
            ident = find_child(child, "identifier")
            if ident is not None and node_text(ident) not in ("self", "cls"):
                params.append(node_text(ident))
        elif child.type == "default_parameter":
            ident = find_child(child, "identifier")
            if ident is not None and node_text(ident) not in ("self", "cls"):
                params.append(node_text(ident))
        elif child.type == "typed_default_parameter":
            ident = find_child(child, "identifier")
            if ident is not None and node_text(ident) not in ("self", "cls"):
                params.append(node_text(ident))
        elif child.type == "list_splat_pattern":
            ident = find_child(child, "identifier")
            if ident is not None:
                params.append("*" + node_text(ident))
        elif child.type == "dictionary_splat_pattern":
            ident = find_child(child, "identifier")
            if ident is not None:
                params.append("**" + node_text(ident))

    return params


def _extract_return_type(node: Any) -> str | None:
    """Extract the return type annotation from a function_definition node."""
    return_type = node.child_by_field_name("return_type")
    if return_type is not None:
        return node_text(return_type)
    return None


def _unwrap_decorated(node: Any) -> Any:
    """Unwrap a ``decorated_definition`` to get the inner definition."""
    if node.type == "decorated_definition":
        inner = find_child(node, "function_definition") or find_child(
            node, "class_definition"
        )
        if inner is not None:
            return inner
    return node


class PythonExtractor:
    """Python extractor for tree-sitter structural analysis and call graph extraction.

    Python has no formal export syntax, so all top-level function and class
    definitions are treated as exports.
    """

    language_ids: list[str] = ["python"]

    def extract_structure(self, root_node: Any) -> dict[str, Any]:
        functions: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        imports: list[dict[str, Any]] = []
        exports: list[dict[str, Any]] = []

        for node in root_node.children:
            if node is None:
                continue

            # Unwrap decorated definitions to get the inner node
            inner = _unwrap_decorated(node)

            if inner.type == "function_definition":
                self._extract_function(inner, functions)
                # Top-level functions are exports in Python
                self._add_export(inner, node, exports)
            elif inner.type == "class_definition":
                self._extract_class(inner, classes)
                # Top-level classes are exports in Python
                self._add_export(inner, node, exports)
            elif inner.type == "import_statement":
                self._extract_import(inner, imports)
            elif inner.type == "import_from_statement":
                self._extract_from_import(inner, imports)

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

            # Track entering function/method definitions
            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    function_stack.append(node_text(name_node))
                    pushed_name = True

            # Extract call expressions
            if node.type == "call":
                callee_node = next(
                    (
                        c
                        for c in node.children
                        if c.type in ("identifier", "attribute")
                    ),
                    None,
                )
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
        self, node: Any, functions: list[dict[str, Any]]
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node)
        return_type = _extract_return_type(node)

        functions.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "params": params,
                "returnType": return_type,
            }
        )

    def _extract_class(self, node: Any, classes: list[dict[str, Any]]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body is not None:
            for member in body.children:
                if member is None:
                    continue

                # Methods: function_definition or decorated_definition wrapping one
                inner_member = _unwrap_decorated(member)
                if inner_member.type == "function_definition":
                    method_name = inner_member.child_by_field_name("name")
                    if method_name is not None:
                        methods.append(node_text(method_name))

                # Properties: type-annotated assignments at class body level
                # e.g., `name: str` or `value: int = 0`. Depending on the grammar
                # version the assignment is either wrapped in an
                # ``expression_statement`` or a direct child of the class body.
                assignment = None
                if member.type == "expression_statement":
                    assignment = find_child(member, "assignment")
                elif member.type == "assignment":
                    assignment = member
                if assignment is not None:
                    type_node = find_child(assignment, "type")
                    name_ident = find_child(assignment, "identifier")
                    if type_node is not None and name_ident is not None:
                        properties.append(node_text(name_ident))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "methods": methods,
                "properties": properties,
            }
        )

    def _extract_import(self, node: Any, imports: list[dict[str, Any]]) -> None:
        # `import os` or `import os.path`; can have multiple: `import os, sys`
        dotted_names = find_children(node, "dotted_name")
        aliased_imports = find_children(node, "aliased_import")

        for dn in dotted_names:
            imports.append(
                {
                    "source": node_text(dn),
                    "specifiers": [node_text(dn)],
                    "lineNumber": node.start_point[0] + 1,
                }
            )

        for ai in aliased_imports:
            dotted_name = find_child(ai, "dotted_name")
            alias = next(
                (c for c in ai.children if c.type == "identifier"), None
            )
            if dotted_name is not None:
                imports.append(
                    {
                        "source": node_text(dotted_name),
                        "specifiers": [
                            node_text(alias)
                            if alias is not None
                            else node_text(dotted_name)
                        ],
                        "lineNumber": node.start_point[0] + 1,
                    }
                )

    def _extract_from_import(
        self, node: Any, imports: list[dict[str, Any]]
    ) -> None:
        # `from pathlib import Path` or `from typing import Optional, List`
        module_node = node.child_by_field_name("module_name")
        source = node_text(module_node) if module_node is not None else ""
        module_node_id = module_node.id if module_node is not None else None

        specifiers: list[str] = []

        # Collect dotted_name specifiers (non-aliased).
        # Skip the module_name dotted_name (compare by node id, not reference).
        all_dotted_names = find_children(node, "dotted_name")
        for dn in all_dotted_names:
            if dn.id == module_node_id:
                continue
            specifiers.append(node_text(dn))

        # Collect aliased imports: `from foo import bar as baz`
        aliased_imports = find_children(node, "aliased_import")
        for ai in aliased_imports:
            # The alias identifier follows the `as` keyword
            alias = next(
                (c for c in ai.children if c.type == "identifier"), None
            )
            if alias is not None:
                specifiers.append(node_text(alias))

        # Handle wildcard imports: `from os import *`
        if find_child(node, "wildcard_import") is not None:
            specifiers.append("*")

        imports.append(
            {
                "source": source,
                "specifiers": specifiers,
                "lineNumber": node.start_point[0] + 1,
            }
        )

    def _add_export(
        self, inner: Any, outer: Any, exports: list[dict[str, Any]]
    ) -> None:
        name_node = inner.child_by_field_name("name")
        if name_node is not None:
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": outer.start_point[0] + 1,
                }
            )
