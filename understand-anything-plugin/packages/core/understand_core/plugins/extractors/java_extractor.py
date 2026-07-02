"""Java language extractor for tree-sitter structural / call-graph analysis.

Port of ``plugins/extractors/java-extractor.ts``.
"""

from __future__ import annotations

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    node_text,
)
from understand_core.plugins.extractors.types import TreeSitterNode


def _extract_params(params_node: TreeSitterNode | None) -> list[str]:
    """Parameter names from a Java ``formal_parameters`` node (incl. varargs)."""
    if not params_node:
        return []
    params: list[str] = []

    declarations = find_children(params_node, "formal_parameter")
    for decl in declarations:
        name_node = decl.child_by_field_name("name")
        if name_node:
            params.append(node_text(name_node))

    # Also handle spread_parameter (varargs): e.g. `String... args`
    spread_params = find_children(params_node, "spread_parameter")
    for spread in spread_params:
        name_node = spread.child_by_field_name("name")
        if name_node:
            params.append(node_text(name_node))

    return params


def _extract_return_type(node: TreeSitterNode) -> str | None:
    """Return type text from a ``method_declaration`` via the ``type`` field."""
    type_node = node.child_by_field_name("type")
    if not type_node:
        return None
    return node_text(type_node)


def _has_modifier(node: TreeSitterNode, modifier: str) -> bool:
    """Whether ``node`` has a ``modifiers`` child containing ``modifier``."""
    modifiers = find_child(node, "modifiers")
    if not modifiers:
        return False
    for child in modifiers.children:
        if child and node_text(child) == modifier:
            return True
    return False


def _extract_scoped_identifier_path(node: TreeSitterNode) -> str:
    """Full dotted path text from a ``scoped_identifier`` node."""
    return node_text(node)


def _last_component(path: str) -> str:
    """Last component of a dotted import path (``java.util.List`` -> ``List``)."""
    parts = path.split(".")
    return parts[-1]


class JavaExtractor:
    """Java extractor for structural analysis and call graph extraction."""

    language_ids: list[str] = ["java"]

    def extract_structure(self, root_node: TreeSitterNode) -> dict:
        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        exports: list[dict] = []

        for node in root_node.children:
            if node is None:
                continue

            if node.type == "import_declaration":
                self._extract_import(node, imports)
            elif node.type == "class_declaration":
                self._extract_class(node, functions, classes, exports)
            elif node.type == "interface_declaration":
                self._extract_interface(node, functions, classes, exports)

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

            # Track entering method/constructor declarations
            if node.type in ("method_declaration", "constructor_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    function_stack.append(node_text(name_node))
                    pushed_name = True

            # Extract method invocations: e.g. fetchFromDb(limit), System.out.println(msg)
            if node.type == "method_invocation":
                if function_stack:
                    callee = self._extract_method_invocation_name(node)
                    if callee:
                        entries.append(
                            {
                                "caller": function_stack[-1],
                                "callee": callee,
                                "lineNumber": node.start_point[0] + 1,
                            }
                        )

            # Extract object creation: e.g. new Foo()
            if node.type == "object_creation_expression":
                if function_stack:
                    type_node = node.child_by_field_name("type")
                    if type_node:
                        entries.append(
                            {
                                "caller": function_stack[-1],
                                "callee": f"new {node_text(type_node)}",
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

    def _extract_method_invocation_name(self, node: TreeSitterNode) -> str | None:
        """Callee name from a ``method_invocation`` (plain or qualified)."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        object_node = node.child_by_field_name("object")
        if object_node:
            return f"{node_text(object_node)}.{node_text(name_node)}"

        return node_text(name_node)

    def _extract_import(
        self,
        node: TreeSitterNode,
        imports: list[dict],
    ) -> None:
        # Check for asterisk (wildcard) import: `import java.util.*;`
        has_asterisk = find_child(node, "asterisk") is not None

        scoped_id = find_child(node, "scoped_identifier")
        if not scoped_id:
            return

        full_path = _extract_scoped_identifier_path(scoped_id)

        if has_asterisk:
            # Wildcard import: source is the full scope, specifier is "*"
            imports.append(
                {
                    "source": full_path,
                    "specifiers": ["*"],
                    "lineNumber": node.start_point[0] + 1,
                }
            )
        else:
            # Regular import: source is the full path, specifier is the last component
            imports.append(
                {
                    "source": full_path,
                    "specifiers": [_last_component(full_path)],
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_class(
        self,
        node: TreeSitterNode,
        functions: list[dict],
        classes: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            self._extract_class_body_members(
                body, methods, properties, functions, exports
            )

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "methods": methods,
                "properties": properties,
            }
        )

        if _has_modifier(node, "public"):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_interface(
        self,
        node: TreeSitterNode,
        functions: list[dict],
        classes: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        methods: list[str] = []
        properties: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            # Interface body contains method_declaration nodes (signatures without bodies)
            method_nodes = find_children(body, "method_declaration")
            for method_node in method_nodes:
                meth_name_node = method_node.child_by_field_name("name")
                if meth_name_node:
                    methods.append(node_text(meth_name_node))

            # Interface can also contain constant_declaration (fields)
            fields = find_children(body, "constant_declaration")
            for field in fields:
                declarators = find_children(field, "variable_declarator")
                for decl in declarators:
                    decl_name = decl.child_by_field_name("name")
                    if decl_name:
                        properties.append(node_text(decl_name))

        classes.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "methods": methods,
                "properties": properties,
            }
        )

        if _has_modifier(node, "public"):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_class_body_members(
        self,
        body: TreeSitterNode,
        methods: list[str],
        properties: list[str],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        """Extract methods, constructors, and fields from a ``class_body`` node."""
        for child in body.children:
            if child is None:
                continue

            if child.type == "method_declaration":
                self._extract_method(child, methods, functions, exports)
            elif child.type == "constructor_declaration":
                self._extract_constructor(child, methods, functions, exports)
            elif child.type == "field_declaration":
                self._extract_field(child, properties, exports)

    def _extract_method(
        self,
        node: TreeSitterNode,
        methods: list[str],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node)
        return_type = _extract_return_type(node)

        methods.append(node_text(name_node))

        functions.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "params": params,
                "returnType": return_type,
            }
        )

        if _has_modifier(node, "public"):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_constructor(
        self,
        node: TreeSitterNode,
        methods: list[str],
        functions: list[dict],
        exports: list[dict],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        params_node = node.child_by_field_name("parameters")
        params = _extract_params(params_node)

        methods.append(node_text(name_node))

        functions.append(
            {
                "name": node_text(name_node),
                "lineRange": [node.start_point[0] + 1, node.end_point[0] + 1],
                "params": params,
                # Constructors have no return type
                "returnType": None,
            }
        )

        if _has_modifier(node, "public"):
            exports.append(
                {
                    "name": node_text(name_node),
                    "lineNumber": node.start_point[0] + 1,
                }
            )

    def _extract_field(
        self,
        node: TreeSitterNode,
        properties: list[str],
        exports: list[dict],
    ) -> None:
        declarators = find_children(node, "variable_declarator")
        for decl in declarators:
            name_node = decl.child_by_field_name("name")
            if name_node:
                properties.append(node_text(name_node))

                if _has_modifier(node, "public"):
                    exports.append(
                        {
                            "name": node_text(name_node),
                            "lineNumber": node.start_point[0] + 1,
                        }
                    )
