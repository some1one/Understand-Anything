"""TypeScript/JavaScript tree-sitter extractor.

Port of ``plugins/extractors/typescript-extractor.ts`` adapted to the Python
``tree_sitter`` API.
"""

from __future__ import annotations

from typing import Any

from understand_core.plugins.extractors.base_extractor import (
    get_string_value,
    node_text,
)


def _extract_params(params_node: Any | None) -> list[str]:
    """Extract parameter names from a formal_parameters node."""
    if not params_node:
        return []
    params: list[str] = []
    for child in params_node.children:
        if child is None:
            continue
        if child.type in ("required_parameter", "optional_parameter"):
            ident = child.child_by_field_name("pattern") or child.child_by_field_name(
                "name"
            )
            if ident is not None:
                params.append(node_text(ident))
            else:
                # Fallback: first identifier child
                for c in child.children:
                    if c is not None and c.type == "identifier":
                        params.append(node_text(c))
                        break
        elif child.type == "identifier":
            # JavaScript parameters (no type annotation)
            params.append(node_text(child))
        elif child.type in ("rest_pattern", "rest_element"):
            ident = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            if ident is not None:
                params.append("..." + node_text(ident))
    return params


def _extract_return_type(node: Any) -> str | None:
    """Extract return type annotation from a function-like node."""
    type_annotation = node.child_by_field_name("return_type")
    if type_annotation is not None and type_annotation.type == "type_annotation":
        text = node_text(type_annotation)
        return text[1:].strip() if text.startswith(":") else text
    return None


def _extract_import_specifiers(import_clause: Any) -> list[str]:
    """Extract import specifiers from an import_clause node."""
    specifiers: list[str] = []
    for child in import_clause.children:
        if child is None:
            continue
        if child.type == "named_imports":
            for spec in child.children:
                if spec is not None and spec.type == "import_specifier":
                    alias = spec.child_by_field_name("alias")
                    name = spec.child_by_field_name("name")
                    if alias is not None:
                        specifiers.append(node_text(alias))
                    elif name is not None:
                        specifiers.append(node_text(name))
                    else:
                        specifiers.append(node_text(spec))
        elif child.type == "namespace_import":
            ident = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            if ident is not None:
                specifiers.append("* as " + node_text(ident))
        elif child.type == "identifier":
            # default import: import foo from '...'
            specifiers.append(node_text(child))
    return specifiers


class TypeScriptExtractor:
    """TypeScript/JavaScript extractor.

    Handles structural analysis and call-graph extraction for TypeScript and
    JavaScript ASTs produced by tree-sitter.
    """

    language_ids: list[str] = ["typescript", "javascript"]

    def extract_structure(self, root_node: Any) -> dict[str, Any]:
        functions: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        imports: list[dict[str, Any]] = []
        exports: list[dict[str, Any]] = []
        exported_names: set[str] = set()

        for node in root_node.children:
            if node is None:
                continue
            self._process_top_level_node(
                node, functions, classes, imports, exports, exported_names
            )

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
            is_function_like = node.type in (
                "function_declaration",
                "method_definition",
                "arrow_function",
                "function_expression",
            )

            pushed_name = False
            if is_function_like:
                name: str | None = None
                if node.type == "function_declaration":
                    name_node = node.child_by_field_name("name") or next(
                        (c for c in node.children if c.type == "identifier"), None
                    )
                    if name_node is not None:
                        name = node_text(name_node)
                elif node.type == "method_definition":
                    name_node = next(
                        (
                            c
                            for c in node.children
                            if c.type == "property_identifier"
                        ),
                        None,
                    )
                    if name_node is not None:
                        name = node_text(name_node)
                elif node.type in ("arrow_function", "function_expression"):
                    parent = node.parent
                    if parent is not None and parent.type == "variable_declarator":
                        name_node = parent.child_by_field_name("name")
                        if name_node is not None:
                            name = node_text(name_node)
                if name:
                    function_stack.append(name)
                    pushed_name = True

            if node.type == "call_expression":
                callee = node.child_by_field_name("function")
                if callee is not None and len(function_stack) > 0:
                    entries.append(
                        {
                            "caller": function_stack[-1],
                            "callee": node_text(callee),
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

    # ---- Private extraction helpers ----

    def _process_top_level_node(
        self,
        node: Any,
        functions: list[dict[str, Any]],
        classes: list[dict[str, Any]],
        imports: list[dict[str, Any]],
        exports: list[dict[str, Any]],
        exported_names: set[str],
    ) -> None:
        if node.type == "function_declaration":
            self._extract_function(node, functions)
        elif node.type == "class_declaration":
            self._extract_class(node, classes)
        elif node.type in ("lexical_declaration", "variable_declaration"):
            self._extract_variable_declarations(node, functions)
        elif node.type == "import_statement":
            self._extract_import(node, imports)
        elif node.type == "export_statement":
            self._process_export_statement(
                node, functions, classes, imports, exports, exported_names
            )

    def _extract_function(
        self, node: Any, functions: list[dict[str, Any]]
    ) -> None:
        name_node = node.child_by_field_name("name") or next(
            (c for c in node.children if c.type == "identifier"), None
        )
        if name_node is None:
            return

        params_node = (
            node.child_by_field_name("parameters")
            or next(
                (c for c in node.children if c.type == "formal_parameters"), None
            )
            or None
        )
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
        name_node = next(
            (
                c
                for c in node.children
                if c.type in ("type_identifier", "identifier")
            ),
            None,
        )
        if name_node is None:
            return

        methods: list[str] = []
        properties: list[str] = []

        class_body = next(
            (c for c in node.children if c.type == "class_body"), None
        )
        if class_body is not None:
            for member in class_body.children:
                if member is None:
                    continue
                if member.type == "method_definition":
                    method_name = next(
                        (
                            c
                            for c in member.children
                            if c.type == "property_identifier"
                        ),
                        None,
                    )
                    if method_name is not None:
                        methods.append(node_text(method_name))
                elif member.type in (
                    "public_field_definition",
                    "property_definition",
                ):
                    prop_name = next(
                        (
                            c
                            for c in member.children
                            if c.type == "property_identifier"
                        ),
                        None,
                    )
                    if prop_name is not None:
                        properties.append(node_text(prop_name))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "methods": methods,
                "properties": properties,
            }
        )

    def _extract_variable_declarations(
        self, node: Any, functions: list[dict[str, Any]]
    ) -> None:
        for child in node.children:
            if child is None or child.type != "variable_declarator":
                continue

            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")

            if (
                name_node is not None
                and value_node is not None
                and value_node.type
                in ("arrow_function", "function_expression", "function")
            ):
                params_node = (
                    value_node.child_by_field_name("parameters")
                    or next(
                        (
                            c
                            for c in value_node.children
                            if c.type == "formal_parameters"
                        ),
                        None,
                    )
                    or None
                )
                params = _extract_params(params_node)
                return_type = _extract_return_type(value_node)

                functions.append(
                    {
                        "name": node_text(name_node),
                        "lineRange": [
                            node.start_point[0] + 1,
                            node.end_point[0] + 1,
                        ],
                        "params": params,
                        "returnType": return_type,
                    }
                )

    def _extract_import(self, node: Any, imports: list[dict[str, Any]]) -> None:
        source_node = next(
            (c for c in node.children if c.type == "string"), None
        )
        if source_node is None:
            return

        source = get_string_value(source_node)
        specifiers: list[str] = []

        import_clause = next(
            (c for c in node.children if c.type == "import_clause"), None
        )
        if import_clause is not None:
            specifiers.extend(_extract_import_specifiers(import_clause))

        imports.append(
            {
                "source": source,
                "specifiers": specifiers,
                "lineNumber": node.start_point[0] + 1,
            }
        )

    def _process_export_statement(
        self,
        node: Any,
        functions: list[dict[str, Any]],
        classes: list[dict[str, Any]],
        _imports: list[dict[str, Any]],
        exports: list[dict[str, Any]],
        exported_names: set[str],
    ) -> None:
        for child in node.children:
            if child is None:
                continue

            if child.type == "function_declaration":
                self._extract_function(child, functions)
                name_node = child.child_by_field_name("name") or next(
                    (c for c in child.children if c.type == "identifier"), None
                )
                is_default = any(c.type == "default" for c in node.children)
                if name_node is not None and node_text(name_node) not in exported_names:
                    exports.append(
                        {
                            "name": node_text(name_node),
                            "lineNumber": node.start_point[0] + 1,
                            "isDefault": is_default,
                        }
                    )
                    exported_names.add(node_text(name_node))
                elif (
                    name_node is None
                    and is_default
                    and "default" not in exported_names
                ):
                    # `export default function () {}` — anonymous default export
                    exports.append(
                        {
                            "name": "default",
                            "lineNumber": node.start_point[0] + 1,
                            "isDefault": True,
                        }
                    )
                    exported_names.add("default")

            elif child.type == "class_declaration":
                self._extract_class(child, classes)
                name_node = next(
                    (
                        c
                        for c in child.children
                        if c.type in ("type_identifier", "identifier")
                    ),
                    None,
                )
                is_default = any(c.type == "default" for c in node.children)
                if name_node is not None and node_text(name_node) not in exported_names:
                    export_name = "default" if is_default else node_text(name_node)
                    exports.append(
                        {
                            "name": export_name,
                            "lineNumber": node.start_point[0] + 1,
                            "isDefault": is_default,
                        }
                    )
                    exported_names.add(export_name)

            elif child.type in ("lexical_declaration", "variable_declaration"):
                self._extract_variable_declarations(child, functions)
                for declarator in child.children:
                    if (
                        declarator is not None
                        and declarator.type == "variable_declarator"
                    ):
                        name_node = declarator.child_by_field_name("name")
                        if (
                            name_node is not None
                            and node_text(name_node) not in exported_names
                        ):
                            exports.append(
                                {
                                    "name": node_text(name_node),
                                    "lineNumber": node.start_point[0] + 1,
                                }
                            )
                            exported_names.add(node_text(name_node))

            elif child.type == "export_clause":
                for spec in child.children:
                    if spec is not None and spec.type == "export_specifier":
                        alias = spec.child_by_field_name("alias")
                        name = spec.child_by_field_name("name")
                        if alias is not None:
                            export_name = node_text(alias)
                        elif name is not None:
                            export_name = node_text(name)
                        else:
                            export_name = node_text(spec)
                        if export_name not in exported_names:
                            exports.append(
                                {
                                    "name": export_name,
                                    "lineNumber": node.start_point[0] + 1,
                                }
                            )
                            exported_names.add(export_name)
