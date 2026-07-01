"""Rust language extractor for tree-sitter structural / call-graph analysis.

Port of ``plugins/extractors/rust-extractor.ts``.
"""

from __future__ import annotations

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    node_text,
)
from understand_core.plugins.extractors.types import TreeSitterNode


def _extract_params(params_node: TreeSitterNode | None) -> list[str]:
    """Parameter names from a Rust ``parameters`` node, skipping ``self``."""
    if not params_node:
        return []
    params: list[str] = []
    for child in params_node.children:
        if child is None:
            continue
        if child.type == "parameter":
            pattern = child.child_by_field_name("pattern")
            if pattern:
                params.append(node_text(pattern))
        # Skip self_parameter — it's the receiver, not a real parameter
    return params


def _extract_return_type(node: TreeSitterNode) -> str | None:
    """Return type text from a ``function_item`` via the ``return_type`` field."""
    return_type = node.child_by_field_name("return_type")
    if return_type:
        return node_text(return_type)
    return None


def _is_public(node: TreeSitterNode) -> bool:
    """Whether ``node`` has a ``visibility_modifier`` starting with ``pub``."""
    vis_mod = find_child(node, "visibility_modifier")
    return vis_mod is not None and node_text(vis_mod).startswith("pub")


def _extract_scoped_path(node: TreeSitterNode) -> tuple[str, str]:
    """Split a ``scoped_identifier`` into ``(path, name)``."""
    if node.type == "scoped_identifier":
        path_node = node.child_by_field_name("path")
        name_node = node.child_by_field_name("name")
        name = node_text(name_node) if name_node else ""
        path = node_text(path_node) if path_node else ""
        return path, name
    # Bare identifier: `use foo;`
    return "", node_text(node)


class RustExtractor:
    """Rust extractor for structural analysis and call graph extraction."""

    language_ids: list[str] = ["rust"]

    def extract_structure(self, root_node: TreeSitterNode) -> dict:
        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        exports: list[dict] = []

        # Track methods per impl type so we can attach them to structs/enums
        methods_by_type: dict[str, list[str]] = {}

        for node in root_node.children:
            if node is None:
                continue

            if node.type == "function_item":
                self._extract_function(node, functions, exports)
            elif node.type == "struct_item":
                self._extract_struct(node, classes, exports)
            elif node.type == "enum_item":
                self._extract_enum(node, classes, exports)
            elif node.type == "trait_item":
                self._extract_trait(node, classes, exports)
            elif node.type == "impl_item":
                self._extract_impl(node, functions, exports, methods_by_type)
            elif node.type == "use_declaration":
                self._extract_use_declaration(node, imports)

        # Attach collected methods to their corresponding structs/enums/traits
        for cls in classes:
            methods = methods_by_type.get(cls["name"])
            if methods:
                cls["methods"].extend(methods)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    def extract_call_graph(self, root_node: TreeSitterNode) -> list[dict]:
        entries: list[dict] = []
        function_stack: list[str] = []

        def walk_for_calls(node: TreeSitterNode) -> None:
            pushed_name = False

            # Track entering function_item declarations
            if node.type == "function_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    function_stack.append(node_text(name_node))
                    pushed_name = True

            # Extract call expressions
            if node.type == "call_expression":
                if function_stack:
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
                    walk_for_calls(child)

            if pushed_name:
                function_stack.pop()

        walk_for_calls(root_node)

        return entries

    # ---- Private helpers ----

    def _extract_callee_name(self, call_node: TreeSitterNode) -> str | None:
        """Callee name from a ``call_expression`` (plain / field / scoped)."""
        func_node = call_node.children[0] if call_node.children else None
        if not func_node:
            return None

        if func_node.type == "identifier":
            return node_text(func_node)

        if func_node.type == "field_expression":
            # e.g., self.validate or obj.method
            field = func_node.child_by_field_name("field")
            value = func_node.child_by_field_name("value")
            if field and value:
                return node_text(value) + "." + node_text(field)

        if func_node.type == "scoped_identifier":
            # e.g., Vec::new
            return node_text(func_node)

        # Fallback: use the full text of the function child
        return node_text(func_node)

    def _extract_function(
        self,
        node: TreeSitterNode,
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
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

        if _is_public(node):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_struct(
        self,
        node: TreeSitterNode,
        classes: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body and body.type == "field_declaration_list":
            fields = find_children(body, "field_declaration")
            for field in fields:
                field_name = find_child(field, "field_identifier")
                if field_name:
                    properties.append(node_text(field_name))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "methods": [],  # Methods are attached later from methods_by_type
                "properties": properties,
            }
        )

        if _is_public(node):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_enum(
        self,
        node: TreeSitterNode,
        classes: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body and body.type == "enum_variant_list":
            variants = find_children(body, "enum_variant")
            for variant in variants:
                variant_name = variant.child_by_field_name("name")
                if variant_name:
                    properties.append(node_text(variant_name))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "methods": [],  # Methods attached later if there's an impl block
                "properties": properties,
            }
        )

        if _is_public(node):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_trait(
        self,
        node: TreeSitterNode,
        classes: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        methods: list[str] = []
        body = find_child(node, "declaration_list")
        if body:
            # Trait bodies contain function_signature_item for method declarations
            sigs = find_children(body, "function_signature_item")
            for sig in sigs:
                sig_name = find_child(sig, "identifier")
                if sig_name:
                    methods.append(node_text(sig_name))
            # Also handle default method implementations (function_item)
            fns = find_children(body, "function_item")
            for fn in fns:
                fn_name = fn.child_by_field_name("name")
                if fn_name:
                    methods.append(node_text(fn_name))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "methods": methods,
                "properties": [],
            }
        )

        if _is_public(node):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_impl(
        self,
        node: TreeSitterNode,
        functions: list[dict],
        exports: list[dict],
        methods_by_type: dict[str, list[str]],
    ) -> None:
        type_node = node.child_by_field_name("type")
        type_name = node_text(type_node) if type_node else None

        body = node.child_by_field_name("body")
        if not body:
            return

        fns = find_children(body, "function_item")
        for fn in fns:
            name_node = fn.child_by_field_name("name")
            if not name_node:
                continue

            params_node = fn.child_by_field_name("parameters")
            params = _extract_params(params_node)
            return_type = _extract_return_type(fn)

            functions.append(
                {
                    "name": node_text(name_node),
                    "lineRange": [fn.start_point[0] + 1, fn.end_point[0] + 1],
                    "params": params,
                    "returnType": return_type,
                }
            )

            # Track method association with the impl type
            if type_name:
                if type_name not in methods_by_type:
                    methods_by_type[type_name] = []
                methods_by_type[type_name].append(node_text(name_node))

            # pub methods inside impl blocks are exports
            if _is_public(fn):
                exports.append(
                    {
                        "name": node_text(name_node),
                        "lineNumber": fn.start_point[0] + 1,
                    }
                )

    def _extract_use_declaration(
        self,
        node: TreeSitterNode,
        imports: list[dict],
    ) -> None:
        argument = node.child_by_field_name("argument")
        if not argument:
            return

        if argument.type == "identifier":
            # `use foo;`
            imports.append(
                {
                    "source": node_text(argument),
                    "specifiers": [node_text(argument)],
                    "lineNumber": node.start_point[0] + 1,
                }
            )

        elif argument.type == "scoped_identifier":
            # `use std::collections::HashMap;`
            path, name = _extract_scoped_path(argument)
            imports.append(
                {
                    "source": path,
                    "specifiers": [name],
                    "lineNumber": node.start_point[0] + 1,
                }
            )

        elif argument.type == "scoped_use_list":
            # `use std::io::{self, Read, Write};`
            path_node = argument.child_by_field_name("path")
            list_node = argument.child_by_field_name("list")
            source = node_text(path_node) if path_node else ""
            specifiers: list[str] = []

            if list_node:
                for ch in list_node.children:
                    if ch is None:
                        continue
                    if ch.type in ("self", "identifier"):
                        specifiers.append(node_text(ch))
                    elif ch.type == "scoped_identifier":
                        # Nested scoped identifier inside a use list
                        specifiers.append(node_text(ch))

            imports.append(
                {
                    "source": source,
                    "specifiers": specifiers,
                    "lineNumber": node.start_point[0] + 1,
                }
            )

        elif argument.type == "use_wildcard":
            # `use std::prelude::*;`
            # The path is the scoped_identifier child
            scoped_id = find_child(argument, "scoped_identifier")
            source = node_text(scoped_id) if scoped_id else ""
            imports.append(
                {
                    "source": source,
                    "specifiers": ["*"],
                    "lineNumber": node.start_point[0] + 1,
                }
            )

        else:
            # Fallback for any unhandled pattern
            imports.append(
                {
                    "source": node_text(argument),
                    "specifiers": [node_text(argument)],
                    "lineNumber": node.start_point[0] + 1,
                }
            )
