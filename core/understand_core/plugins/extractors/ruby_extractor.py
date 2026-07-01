"""Ruby language extractor for tree-sitter structural / call-graph analysis.

Port of ``plugins/extractors/ruby-extractor.ts``.
"""

from __future__ import annotations

import re

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    node_text,
)
from understand_core.plugins.extractors.types import TreeSitterNode

# Method names that Ruby uses for imports.
IMPORT_METHODS = {"require", "require_relative"}

# Method names that define class properties (attr_* macros).
ATTR_METHODS = {"attr_accessor", "attr_reader", "attr_writer"}

_QUOTE_RE = re.compile(r"^['\"`]|['\"`]$")


def _extract_params(params_node: TreeSitterNode | None) -> list[str]:
    """Parameter names from a Ruby ``method_parameters`` node."""
    if not params_node:
        return []
    params: list[str] = []

    for child in params_node.children:
        if not child:
            continue

        if child.type == "identifier":
            params.append(node_text(child))
        elif child.type == "optional_parameter":
            ident = child.child_by_field_name("name")
            if ident:
                params.append(node_text(ident))
        elif child.type == "splat_parameter":
            ident = child.child_by_field_name("name")
            if ident:
                params.append("*" + node_text(ident))
        elif child.type == "hash_splat_parameter":
            ident = child.child_by_field_name("name")
            if ident:
                params.append("**" + node_text(ident))
        elif child.type == "block_parameter":
            ident = child.child_by_field_name("name")
            if ident:
                params.append("&" + node_text(ident))

    return params


def _extract_attr_properties(call_node: TreeSitterNode) -> list[str]:
    """Property names from ``attr_accessor``/``attr_reader``/``attr_writer`` calls."""
    properties: list[str] = []
    args = call_node.child_by_field_name("arguments")
    if not args:
        return properties

    for child in args.children:
        if child and child.type == "simple_symbol":
            # Strip leading colon from `:name` -> `name`
            properties.append(node_text(child)[1:])

    return properties


def _get_string_content(node: TreeSitterNode) -> str:
    """String value from a Ruby string node (``string_content`` child)."""
    content = find_child(node, "string_content")
    if content:
        return node_text(content)
    # Fallback: strip surrounding quotes
    return _QUOTE_RE.sub("", node_text(node))


class RubyExtractor:
    """Ruby extractor for tree-sitter structural analysis and call-graph extraction."""

    language_ids: list[str] = ["ruby"]

    def extract_structure(self, root_node: TreeSitterNode) -> dict:
        """Extract functions, classes, imports, and exports from a Ruby file."""
        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        exports: list[dict] = []

        for node in root_node.children:
            if not node:
                continue

            if node.type == "method":
                self._extract_method(node, functions)
                exports.append({
                    "name": self._get_method_name(node),
                    "lineNumber": node.start_point[0] + 1,
                })
            elif node.type == "singleton_method":
                self._extract_singleton_method(node, functions)
                exports.append({
                    "name": "self." + self._get_singleton_method_name(node),
                    "lineNumber": node.start_point[0] + 1,
                })
            elif node.type == "class":
                self._extract_class(node, classes, functions)
                exports.append({
                    "name": self._get_class_name(node),
                    "lineNumber": node.start_point[0] + 1,
                })
            elif node.type == "module":
                self._extract_module(node, classes, functions)
                exports.append({
                    "name": self._get_module_name(node),
                    "lineNumber": node.start_point[0] + 1,
                })
            elif node.type == "call":
                self._extract_top_level_call(node, imports)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    def extract_call_graph(self, root_node: TreeSitterNode) -> list[dict]:
        """Extract caller/callee relationships from a Ruby file."""
        entries: list[dict] = []
        function_stack: list[str] = []

        def walk_for_calls(node: TreeSitterNode) -> None:
            pushed_name = False

            if node.type == "method":
                name_node = node.child_by_field_name("name")
                if name_node:
                    function_stack.append(node_text(name_node))
                    pushed_name = True
            elif node.type == "singleton_method":
                name_node = node.child_by_field_name("name")
                if name_node:
                    function_stack.append("self." + node_text(name_node))
                    pushed_name = True

            if node.type == "call":
                method_node = node.child_by_field_name("method")
                if method_node and len(function_stack) > 0:
                    method_name = node_text(method_node)

                    if method_name not in IMPORT_METHODS and method_name not in ATTR_METHODS:
                        receiver_node = node.child_by_field_name("receiver")
                        callee = (
                            node_text(receiver_node) + "." + method_name
                            if receiver_node
                            else method_name
                        )

                        entries.append({
                            "caller": function_stack[-1],
                            "callee": callee,
                            "lineNumber": node.start_point[0] + 1,
                        })

            # Ruby bare method calls without arguments (e.g., `setup`) parse as
            # `identifier` nodes inside `body_statement`, not as `call` nodes.
            if (
                node.type == "identifier"
                and node.parent
                and node.parent.type == "body_statement"
                and len(function_stack) > 0
            ):
                entries.append({
                    "caller": function_stack[-1],
                    "callee": node_text(node),
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

    def _get_method_name(self, node: TreeSitterNode) -> str:
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node else ""

    def _get_singleton_method_name(self, node: TreeSitterNode) -> str:
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node else ""

    def _get_class_name(self, node: TreeSitterNode) -> str:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return ""
        # Can be `constant` ("Foo") or `scope_resolution` ("Foo::Bar")
        return node_text(name_node)

    def _get_module_name(self, node: TreeSitterNode) -> str:
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node else ""

    def _extract_method(self, node: TreeSitterNode, functions: list[dict]) -> None:
        """Extract a ``method`` node."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node or None)

        functions.append({
            "name": node_text(name_node),
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "params": params,
            "returnType": None,
        })

    def _extract_singleton_method(self, node: TreeSitterNode, functions: list[dict]) -> None:
        """Extract a ``singleton_method`` (``def self.foo``) node."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node or None)

        functions.append({
            "name": "self." + node_text(name_node),
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "params": params,
            "returnType": None,
        })

    def _extract_class(
        self,
        node: TreeSitterNode,
        classes: list[dict],
        functions: list[dict],
    ) -> None:
        """Extract a ``class`` node."""
        name = self._get_class_name(node)
        if not name:
            return

        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            self._extract_class_body(body, methods, properties, functions)

        classes.append({
            "name": name,
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "methods": methods,
            "properties": properties,
        })

    def _extract_module(
        self,
        node: TreeSitterNode,
        classes: list[dict],
        functions: list[dict],
    ) -> None:
        """Extract a ``module`` node (mapped to classes)."""
        name = self._get_module_name(node)
        if not name:
            return

        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            self._extract_class_body(body, methods, properties, functions)

        classes.append({
            "name": name,
            "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
            "methods": methods,
            "properties": properties,
        })

    def _extract_class_body(
        self,
        body: TreeSitterNode,
        methods: list[str],
        properties: list[str],
        functions: list[dict],
    ) -> None:
        """Extract methods and properties from a class/module ``body_statement``."""
        for member in body.children:
            if not member:
                continue

            if member.type == "method":
                name_node = member.child_by_field_name("name")
                if name_node:
                    methods.append(node_text(name_node))
                    self._extract_method(member, functions)
            elif member.type == "singleton_method":
                name_node = member.child_by_field_name("name")
                if name_node:
                    methods.append("self." + node_text(name_node))
                    self._extract_singleton_method(member, functions)
            elif member.type == "call":
                method_node = member.child_by_field_name("method")
                if method_node and node_text(method_node) in ATTR_METHODS:
                    properties.extend(_extract_attr_properties(member))

    def _extract_top_level_call(self, node: TreeSitterNode, imports: list[dict]) -> None:
        """Handle top-level ``call`` nodes: extract require/require_relative imports."""
        method_node = node.child_by_field_name("method")
        if not method_node:
            return

        if node_text(method_node) in IMPORT_METHODS:
            args = node.child_by_field_name("arguments")
            if not args:
                return

            first_arg = find_child(args, "string")
            if first_arg:
                source = _get_string_content(first_arg)
                imports.append({
                    "source": source,
                    "specifiers": [source],
                    "lineNumber": node.start_point[0] + 1,
                })
