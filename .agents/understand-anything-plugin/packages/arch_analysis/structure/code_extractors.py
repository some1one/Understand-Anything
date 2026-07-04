"""Tree-sitter language extractors (port of core/src/plugins/extractors/*.ts).

Each extractor exposes ``language_ids`` and two methods:
- ``extract_structure(root) -> StructuralAnalysis``
- ``extract_call_graph(root) -> list[dict]``  (entries: caller/callee/lineNumber)

These mirror the TypeScript extractors node-type for node-type. ``node.text`` is
decoded via :func:`base.txt`; line numbers are ``start_point.row + 1``.
"""

from __future__ import annotations

from tree_sitter import Node

from .base import (
    StructuralAnalysis,
    child_field,
    find_child,
    find_children,
    find_descendant_child,
    make_class,
    make_export,
    make_function,
    make_import,
    txt,
)


def _cg(caller: str, callee: str, line: int) -> dict:
    return {"caller": caller, "callee": callee, "lineNumber": line}


# ===========================================================================
# TypeScript / JavaScript
# ===========================================================================


def _ts_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for child in params_node.children:
        if child is None:
            continue
        if child.type in ("required_parameter", "optional_parameter"):
            ident = child.child_by_field_name("pattern") or child.child_by_field_name("name")
            if ident is not None:
                params.append(txt(ident))
            else:
                for c in child.children:
                    if c is not None and c.type == "identifier":
                        params.append(txt(c))
                        break
        elif child.type == "identifier":
            params.append(txt(child))
        elif child.type in ("rest_pattern", "rest_element"):
            ident = find_descendant_child(child, lambda c: c.type == "identifier")
            if ident is not None:
                params.append("..." + txt(ident))
    return params


def _ts_return_type(node: Node) -> str | None:
    ta = node.child_by_field_name("return_type")
    if ta is not None and ta.type == "type_annotation":
        text = txt(ta)
        return text[1:].strip() if text.startswith(":") else text
    return None


def _ts_import_specifiers(import_clause: Node) -> list[str]:
    specifiers: list[str] = []
    for child in import_clause.children:
        if child is None:
            continue
        if child.type == "named_imports":
            for spec in child.children:
                if spec is not None and spec.type == "import_specifier":
                    alias = spec.child_by_field_name("alias")
                    name = spec.child_by_field_name("name")
                    specifiers.append(txt(alias) if alias else (txt(name) if name else txt(spec)))
        elif child.type == "namespace_import":
            ident = find_descendant_child(child, lambda c: c.type == "identifier")
            if ident is not None:
                specifiers.append("* as " + txt(ident))
        elif child.type == "identifier":
            specifiers.append(txt(child))
    return specifiers


class TypeScriptExtractor:
    language_ids = ["typescript", "javascript"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        exported_names: set[str] = set()
        for node in root.children:
            if node is None:
                continue
            self._top_level(node, a, exported_names)
        return a

    def _top_level(self, node: Node, a: StructuralAnalysis, exported: set[str]) -> None:
        t = node.type
        if t == "function_declaration":
            self._extract_function(node, a.functions)
        elif t == "class_declaration":
            self._extract_class(node, a.classes)
        elif t in ("lexical_declaration", "variable_declaration"):
            self._extract_var_decls(node, a.functions)
        elif t == "import_statement":
            self._extract_import(node, a.imports)
        elif t == "export_statement":
            self._process_export(node, a, exported)

    def _extract_function(self, node: Node, functions: list[dict]) -> None:
        name_node = node.child_by_field_name("name") or find_descendant_child(
            node, lambda c: c.type == "identifier"
        )
        if name_node is None:
            return
        params_node = node.child_by_field_name("parameters") or find_descendant_child(
            node, lambda c: c.type == "formal_parameters"
        )
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _ts_extract_params(params_node),
                _ts_return_type(node),
            )
        )

    def _extract_class(self, node: Node, classes: list[dict]) -> None:
        name_node = find_descendant_child(
            node, lambda c: c.type in ("type_identifier", "identifier")
        )
        if name_node is None:
            return
        methods: list[str] = []
        properties: list[str] = []
        class_body = find_descendant_child(node, lambda c: c.type == "class_body")
        if class_body is not None:
            for member in class_body.children:
                if member is None:
                    continue
                if member.type == "method_definition":
                    mn = find_descendant_child(member, lambda c: c.type == "property_identifier")
                    if mn is not None:
                        methods.append(txt(mn))
                elif member.type in ("public_field_definition", "property_definition"):
                    pn = find_descendant_child(member, lambda c: c.type == "property_identifier")
                    if pn is not None:
                        properties.append(txt(pn))
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )

    def _extract_var_decls(self, node: Node, functions: list[dict]) -> None:
        for child in node.children:
            if child is None or child.type != "variable_declarator":
                continue
            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if (
                name_node is not None
                and value_node is not None
                and value_node.type in ("arrow_function", "function_expression", "function")
            ):
                params_node = value_node.child_by_field_name("parameters") or find_descendant_child(
                    value_node, lambda c: c.type == "formal_parameters"
                )
                functions.append(
                    make_function(
                        txt(name_node),
                        node.start_point[0] + 1,
                        node.end_point[0] + 1,
                        _ts_extract_params(params_node),
                        _ts_return_type(value_node),
                    )
                )

    def _extract_import(self, node: Node, imports: list[dict]) -> None:
        source_node = find_descendant_child(node, lambda c: c.type == "string")
        if source_node is None:
            return
        from .base import get_string_value

        source = get_string_value(source_node)
        specifiers: list[str] = []
        import_clause = find_descendant_child(node, lambda c: c.type == "import_clause")
        if import_clause is not None:
            specifiers.extend(_ts_import_specifiers(import_clause))
        imports.append(make_import(source, specifiers, node.start_point[0] + 1))

    def _process_export(self, node: Node, a: StructuralAnalysis, exported: set[str]) -> None:
        line = node.start_point[0] + 1
        for child in node.children:
            if child is None:
                continue
            if child.type == "function_declaration":
                self._extract_function(child, a.functions)
                name_node = child.child_by_field_name("name") or find_descendant_child(
                    child, lambda c: c.type == "identifier"
                )
                is_default = any(c is not None and c.type == "default" for c in node.children)
                if name_node is not None and txt(name_node) not in exported:
                    a.exports.append(make_export(txt(name_node), line, is_default))
                    exported.add(txt(name_node))
                elif name_node is None and is_default and "default" not in exported:
                    a.exports.append(make_export("default", line, True))
                    exported.add("default")
            elif child.type == "class_declaration":
                self._extract_class(child, a.classes)
                name_node = find_descendant_child(
                    child, lambda c: c.type in ("type_identifier", "identifier")
                )
                is_default = any(c is not None and c.type == "default" for c in node.children)
                if name_node is not None and txt(name_node) not in exported:
                    export_name = "default" if is_default else txt(name_node)
                    a.exports.append(make_export(export_name, line, is_default))
                    exported.add(export_name)
            elif child.type in ("lexical_declaration", "variable_declaration"):
                self._extract_var_decls(child, a.functions)
                for declarator in child.children:
                    if declarator is not None and declarator.type == "variable_declarator":
                        name_node = declarator.child_by_field_name("name")
                        if name_node is not None and txt(name_node) not in exported:
                            a.exports.append(make_export(txt(name_node), line))
                            exported.add(txt(name_node))
            elif child.type == "export_clause":
                for spec in child.children:
                    if spec is not None and spec.type == "export_specifier":
                        alias = spec.child_by_field_name("alias")
                        name = spec.child_by_field_name("name")
                        export_name = txt(alias) if alias else (txt(name) if name else txt(spec))
                        if export_name not in exported:
                            a.exports.append(make_export(export_name, line))
                            exported.add(export_name)

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            is_fn = node.type in (
                "function_declaration",
                "method_definition",
                "arrow_function",
                "function_expression",
            )
            pushed = False
            if is_fn:
                name: str | None = None
                if node.type == "function_declaration":
                    nn = node.child_by_field_name("name") or find_descendant_child(
                        node, lambda c: c.type == "identifier"
                    )
                    name = txt(nn) if nn else None
                elif node.type == "method_definition":
                    nn = find_descendant_child(node, lambda c: c.type == "property_identifier")
                    name = txt(nn) if nn else None
                elif node.type in ("arrow_function", "function_expression"):
                    parent = node.parent
                    if parent is not None and parent.type == "variable_declarator":
                        nn = parent.child_by_field_name("name")
                        name = txt(nn) if nn else None
                if name:
                    stack.append(name)
                    pushed = True
            if node.type == "call_expression":
                callee = node.child_by_field_name("function")
                if callee is not None and stack:
                    entries.append(_cg(stack[-1], txt(callee), node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# Python
# ===========================================================================


def _py_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for child in params_node.children:
        if child is None:
            continue
        t = child.type
        if t == "identifier":
            if txt(child) not in ("self", "cls"):
                params.append(txt(child))
        elif t in ("typed_parameter", "default_parameter", "typed_default_parameter"):
            ident = find_child(child, "identifier")
            if ident is not None and txt(ident) not in ("self", "cls"):
                params.append(txt(ident))
        elif t == "list_splat_pattern":
            ident = find_child(child, "identifier")
            if ident is not None:
                params.append("*" + txt(ident))
        elif t == "dictionary_splat_pattern":
            ident = find_child(child, "identifier")
            if ident is not None:
                params.append("**" + txt(ident))
    return params


def _py_unwrap_decorated(node: Node) -> Node:
    if node.type == "decorated_definition":
        inner = find_child(node, "function_definition") or find_child(node, "class_definition")
        if inner is not None:
            return inner
    return node


class PythonExtractor:
    language_ids = ["python"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        for node in root.children:
            if node is None:
                continue
            inner = _py_unwrap_decorated(node)
            t = inner.type
            if t == "function_definition":
                self._extract_function(inner, a.functions)
                self._add_export(inner, node, a.exports)
            elif t == "class_definition":
                self._extract_class(inner, a.classes)
                self._add_export(inner, node, a.exports)
            elif t == "import_statement":
                self._extract_import(inner, a.imports)
            elif t == "import_from_statement":
                self._extract_from_import(inner, a.imports)
        return a

    def _extract_function(self, node: Node, functions: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        params_node = node.child_by_field_name("parameters")
        rt = node.child_by_field_name("return_type")
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _py_extract_params(params_node),
                txt(rt) if rt is not None else None,
            )
        )

    def _extract_class(self, node: Node, classes: list[dict]) -> None:
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
                inner = _py_unwrap_decorated(member)
                if inner.type == "function_definition":
                    mn = inner.child_by_field_name("name")
                    if mn is not None:
                        methods.append(txt(mn))
                # Type-annotated class-level assignment -> property.
                # Core's grammar wraps the assignment in an expression_statement;
                # the grammar shipped here exposes the `assignment` directly as a
                # body member. Handle both so `name: str` is captured either way.
                assignment = None
                if member.type == "expression_statement":
                    assignment = find_child(member, "assignment")
                elif member.type == "assignment":
                    assignment = member
                if assignment is not None:
                    type_node = find_child(assignment, "type")
                    name_ident = find_child(assignment, "identifier")
                    if type_node is not None and name_ident is not None:
                        properties.append(txt(name_ident))
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )

    def _extract_import(self, node: Node, imports: list[dict]) -> None:
        line = node.start_point[0] + 1
        for dn in find_children(node, "dotted_name"):
            imports.append(make_import(txt(dn), [txt(dn)], line))
        for ai in find_children(node, "aliased_import"):
            dotted_name = find_child(ai, "dotted_name")
            alias = find_descendant_child(ai, lambda c: c.type == "identifier")
            if dotted_name is not None:
                imports.append(
                    make_import(txt(dotted_name), [txt(alias) if alias else txt(dotted_name)], line)
                )

    def _extract_from_import(self, node: Node, imports: list[dict]) -> None:
        line = node.start_point[0] + 1
        module_node = node.child_by_field_name("module_name")
        source = txt(module_node) if module_node is not None else ""
        module_id = module_node.id if module_node is not None else None
        specifiers: list[str] = []
        for dn in find_children(node, "dotted_name"):
            if module_id is not None and dn.id == module_id:
                continue
            specifiers.append(txt(dn))
        for ai in find_children(node, "aliased_import"):
            alias = find_descendant_child(ai, lambda c: c.type == "identifier")
            if alias is not None:
                specifiers.append(txt(alias))
        if find_child(node, "wildcard_import") is not None:
            specifiers.append("*")
        imports.append(make_import(source, specifiers, line))

    def _add_export(self, inner: Node, outer: Node, exports: list[dict]) -> None:
        name_node = inner.child_by_field_name("name")
        if name_node is not None:
            exports.append(make_export(txt(name_node), outer.start_point[0] + 1))

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type == "function_definition":
                nn = node.child_by_field_name("name")
                if nn is not None:
                    stack.append(txt(nn))
                    pushed = True
            if node.type == "call":
                callee = next(
                    (c for c in node.children if c is not None and c.type in ("identifier", "attribute")),
                    None,
                )
                if callee is not None and stack:
                    entries.append(_cg(stack[-1], txt(callee), node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# Go
# ===========================================================================


def _go_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for decl in find_children(params_node, "parameter_declaration"):
        for child in decl.children:
            if child is not None and child.type == "identifier":
                params.append(txt(child))
    return params


def _go_result_type(node: Node) -> str | None:
    result = node.child_by_field_name("result")
    return txt(result) if result is not None else None


def _go_receiver_type(receiver_node: Node) -> str | None:
    decl = find_child(receiver_node, "parameter_declaration")
    if decl is None:
        return None
    for child in decl.children:
        if child is None:
            continue
        if child.type == "type_identifier":
            return txt(child)
        if child.type == "pointer_type":
            tid = find_child(child, "type_identifier")
            if tid is not None:
                return txt(tid)
    return None


def _go_is_exported(name: str) -> bool:
    return len(name) > 0 and "A" <= name[0] <= "Z"


class GoExtractor:
    language_ids = ["go"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        methods_by_receiver: dict[str, list[str]] = {}
        for node in root.children:
            if node is None:
                continue
            t = node.type
            if t == "function_declaration":
                self._extract_function(node, a.functions, a.exports)
            elif t == "method_declaration":
                self._extract_method(node, a.functions, a.exports, methods_by_receiver)
            elif t == "type_declaration":
                self._extract_type_declaration(node, a.classes, a.exports)
            elif t == "import_declaration":
                self._extract_import_declaration(node, a.imports)
        for cls in a.classes:
            methods = methods_by_receiver.get(cls["name"])
            if methods:
                cls["methods"].extend(methods)
        return a

    def _extract_function(self, node: Node, functions: list[dict], exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _go_extract_params(node.child_by_field_name("parameters")),
                _go_result_type(node),
            )
        )
        if _go_is_exported(txt(name_node)):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_method(self, node: Node, functions: list[dict], exports: list[dict],
                        methods_by_receiver: dict[str, list[str]]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _go_extract_params(node.child_by_field_name("parameters")),
                _go_result_type(node),
            )
        )
        receiver_node = node.child_by_field_name("receiver")
        if receiver_node is not None:
            receiver_type = _go_receiver_type(receiver_node)
            if receiver_type:
                methods_by_receiver.setdefault(receiver_type, []).append(txt(name_node))
        if _go_is_exported(txt(name_node)):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_type_declaration(self, node: Node, classes: list[dict], exports: list[dict]) -> None:
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

    def _extract_struct(self, decl_node: Node, name_node: Node, struct_node: Node,
                        classes: list[dict], exports: list[dict]) -> None:
        properties: list[str] = []
        field_list = find_child(struct_node, "field_declaration_list")
        if field_list is not None:
            for field in find_children(field_list, "field_declaration"):
                for child in field.children:
                    if child is not None and child.type == "field_identifier":
                        properties.append(txt(child))
        classes.append(
            make_class(txt(name_node), decl_node.start_point[0] + 1, decl_node.end_point[0] + 1, [], properties)
        )
        if _go_is_exported(txt(name_node)):
            exports.append(make_export(txt(name_node), decl_node.start_point[0] + 1))

    def _extract_interface(self, decl_node: Node, name_node: Node, interface_node: Node,
                           classes: list[dict], exports: list[dict]) -> None:
        methods: list[str] = []
        for elem in find_children(interface_node, "method_elem"):
            mn = elem.child_by_field_name("name")
            if mn is not None:
                methods.append(txt(mn))
        classes.append(
            make_class(txt(name_node), decl_node.start_point[0] + 1, decl_node.end_point[0] + 1, methods, [])
        )
        if _go_is_exported(txt(name_node)):
            exports.append(make_export(txt(name_node), decl_node.start_point[0] + 1))

    def _extract_import_declaration(self, node: Node, imports: list[dict]) -> None:
        spec_list = find_child(node, "import_spec_list")
        if spec_list is not None:
            for spec in find_children(spec_list, "import_spec"):
                self._extract_import_spec(spec, imports)
        else:
            spec = find_child(node, "import_spec")
            if spec is not None:
                self._extract_import_spec(spec, imports)

    def _extract_import_spec(self, spec: Node, imports: list[dict]) -> None:
        path_node = spec.child_by_field_name("path")
        if path_node is None:
            return
        path_content = find_child(path_node, "interpreted_string_literal_content")
        if path_content is not None:
            source = txt(path_content)
        else:
            source = txt(path_node).strip('"')
        name_node = spec.child_by_field_name("name")
        if name_node is not None:
            specifier = txt(name_node)
        else:
            specifier = source.split("/")[-1]
        imports.append(make_import(source, [specifier], spec.start_point[0] + 1))

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type in ("function_declaration", "method_declaration"):
                nn = node.child_by_field_name("name")
                if nn is not None:
                    stack.append(txt(nn))
                    pushed = True
            if node.type == "call_expression":
                callee = node.child_by_field_name("function")
                if callee is not None and stack:
                    entries.append(_cg(stack[-1], txt(callee), node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# Rust
# ===========================================================================


def _rust_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for child in params_node.children:
        if child is not None and child.type == "parameter":
            pattern = child.child_by_field_name("pattern")
            if pattern is not None:
                params.append(txt(pattern))
    return params


def _rust_is_public(node: Node) -> bool:
    vis = find_child(node, "visibility_modifier")
    return vis is not None and txt(vis).startswith("pub")


def _rust_scoped_path(node: Node) -> tuple[str, str]:
    if node.type == "scoped_identifier":
        path_node = node.child_by_field_name("path")
        name_node = node.child_by_field_name("name")
        return (txt(path_node) if path_node else "", txt(name_node) if name_node else "")
    return ("", txt(node))


class RustExtractor:
    language_ids = ["rust"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        methods_by_type: dict[str, list[str]] = {}
        for node in root.children:
            if node is None:
                continue
            t = node.type
            if t == "function_item":
                self._extract_function(node, a.functions, a.exports)
            elif t == "struct_item":
                self._extract_struct(node, a.classes, a.exports)
            elif t == "enum_item":
                self._extract_enum(node, a.classes, a.exports)
            elif t == "trait_item":
                self._extract_trait(node, a.classes, a.exports)
            elif t == "impl_item":
                self._extract_impl(node, a.functions, a.exports, methods_by_type)
            elif t == "use_declaration":
                self._extract_use(node, a.imports)
        for cls in a.classes:
            methods = methods_by_type.get(cls["name"])
            if methods:
                cls["methods"].extend(methods)
        return a

    def _extract_function(self, node: Node, functions: list[dict], exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        rt = node.child_by_field_name("return_type")
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _rust_extract_params(node.child_by_field_name("parameters")),
                txt(rt) if rt is not None else None,
            )
        )
        if _rust_is_public(node):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_struct(self, node: Node, classes: list[dict], exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None and body.type == "field_declaration_list":
            for field in find_children(body, "field_declaration"):
                fn = find_child(field, "field_identifier")
                if fn is not None:
                    properties.append(txt(fn))
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, [], properties)
        )
        if _rust_is_public(node):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_enum(self, node: Node, classes: list[dict], exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None and body.type == "enum_variant_list":
            for variant in find_children(body, "enum_variant"):
                vn = variant.child_by_field_name("name")
                if vn is not None:
                    properties.append(txt(vn))
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, [], properties)
        )
        if _rust_is_public(node):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_trait(self, node: Node, classes: list[dict], exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        methods: list[str] = []
        body = find_child(node, "declaration_list")
        if body is not None:
            for sig in find_children(body, "function_signature_item"):
                sn = find_child(sig, "identifier")
                if sn is not None:
                    methods.append(txt(sn))
            for fn in find_children(body, "function_item"):
                fnn = fn.child_by_field_name("name")
                if fnn is not None:
                    methods.append(txt(fnn))
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, methods, [])
        )
        if _rust_is_public(node):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_impl(self, node: Node, functions: list[dict], exports: list[dict],
                      methods_by_type: dict[str, list[str]]) -> None:
        type_node = node.child_by_field_name("type")
        type_name = txt(type_node) if type_node is not None else None
        body = node.child_by_field_name("body")
        if body is None:
            return
        for fn in find_children(body, "function_item"):
            name_node = fn.child_by_field_name("name")
            if name_node is None:
                continue
            rt = fn.child_by_field_name("return_type")
            functions.append(
                make_function(
                    txt(name_node),
                    fn.start_point[0] + 1,
                    fn.end_point[0] + 1,
                    _rust_extract_params(fn.child_by_field_name("parameters")),
                    txt(rt) if rt is not None else None,
                )
            )
            if type_name:
                methods_by_type.setdefault(type_name, []).append(txt(name_node))
            if _rust_is_public(fn):
                exports.append(make_export(txt(name_node), fn.start_point[0] + 1))

    def _extract_use(self, node: Node, imports: list[dict]) -> None:
        argument = node.child_by_field_name("argument")
        if argument is None:
            return
        line = node.start_point[0] + 1
        t = argument.type
        if t == "identifier":
            imports.append(make_import(txt(argument), [txt(argument)], line))
        elif t == "scoped_identifier":
            path, name = _rust_scoped_path(argument)
            imports.append(make_import(path, [name], line))
        elif t == "scoped_use_list":
            path_node = argument.child_by_field_name("path")
            list_node = argument.child_by_field_name("list")
            source = txt(path_node) if path_node is not None else ""
            specifiers: list[str] = []
            if list_node is not None:
                for ch in list_node.children:
                    if ch is None:
                        continue
                    if ch.type in ("self", "identifier", "scoped_identifier"):
                        specifiers.append(txt(ch))
            imports.append(make_import(source, specifiers, line))
        elif t == "use_wildcard":
            scoped_id = find_child(argument, "scoped_identifier")
            source = txt(scoped_id) if scoped_id is not None else ""
            imports.append(make_import(source, ["*"], line))
        else:
            imports.append(make_import(txt(argument), [txt(argument)], line))

    def _callee_name(self, call_node: Node) -> str | None:
        func_node = call_node.child(0)
        if func_node is None:
            return None
        if func_node.type == "identifier":
            return txt(func_node)
        if func_node.type == "field_expression":
            field = func_node.child_by_field_name("field")
            value = func_node.child_by_field_name("value")
            if field is not None and value is not None:
                return txt(value) + "." + txt(field)
        if func_node.type == "scoped_identifier":
            return txt(func_node)
        return txt(func_node)

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type == "function_item":
                nn = node.child_by_field_name("name")
                if nn is not None:
                    stack.append(txt(nn))
                    pushed = True
            if node.type == "call_expression" and stack:
                callee = self._callee_name(node)
                if callee:
                    entries.append(_cg(stack[-1], callee, node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# Java
# ===========================================================================


def _java_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for decl in find_children(params_node, "formal_parameter"):
        nn = decl.child_by_field_name("name")
        if nn is not None:
            params.append(txt(nn))
    for spread in find_children(params_node, "spread_parameter"):
        nn = spread.child_by_field_name("name")
        if nn is not None:
            params.append(txt(nn))
    return params


def _java_has_modifier(node: Node, modifier: str) -> bool:
    modifiers = find_child(node, "modifiers")
    if modifiers is None:
        return False
    return any(c is not None and txt(c) == modifier for c in modifiers.children)


def _last_component(path: str, sep: str = ".") -> str:
    parts = path.split(sep)
    return parts[-1]


class JavaExtractor:
    language_ids = ["java"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        for node in root.children:
            if node is None:
                continue
            t = node.type
            if t == "import_declaration":
                self._extract_import(node, a.imports)
            elif t == "class_declaration":
                self._extract_class(node, a.functions, a.classes, a.exports)
            elif t == "interface_declaration":
                self._extract_interface(node, a.functions, a.classes, a.exports)
        return a

    def _extract_import(self, node: Node, imports: list[dict]) -> None:
        has_asterisk = find_child(node, "asterisk") is not None
        scoped_id = find_child(node, "scoped_identifier")
        if scoped_id is None:
            return
        full_path = txt(scoped_id)
        line = node.start_point[0] + 1
        if has_asterisk:
            imports.append(make_import(full_path, ["*"], line))
        else:
            imports.append(make_import(full_path, [_last_component(full_path)], line))

    def _extract_class(self, node: Node, functions: list[dict], classes: list[dict],
                       exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        methods: list[str] = []
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None:
            self._class_body(body, methods, properties, functions, exports)
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )
        if _java_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_interface(self, node: Node, functions: list[dict], classes: list[dict],
                           exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        methods: list[str] = []
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None:
            for method_node in find_children(body, "method_declaration"):
                mn = method_node.child_by_field_name("name")
                if mn is not None:
                    methods.append(txt(mn))
            for field in find_children(body, "constant_declaration"):
                for decl in find_children(field, "variable_declarator"):
                    dn = decl.child_by_field_name("name")
                    if dn is not None:
                        properties.append(txt(dn))
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )
        if _java_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _class_body(self, body: Node, methods: list[str], properties: list[str],
                    functions: list[dict], exports: list[dict]) -> None:
        for child in body.children:
            if child is None:
                continue
            if child.type == "method_declaration":
                self._extract_method(child, methods, functions, exports)
            elif child.type == "constructor_declaration":
                self._extract_constructor(child, methods, functions, exports)
            elif child.type == "field_declaration":
                self._extract_field(child, properties, exports)

    def _extract_method(self, node: Node, methods: list[str], functions: list[dict],
                        exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        type_node = node.child_by_field_name("type")
        methods.append(txt(name_node))
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _java_extract_params(node.child_by_field_name("parameters")),
                txt(type_node) if type_node is not None else None,
            )
        )
        if _java_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_constructor(self, node: Node, methods: list[str], functions: list[dict],
                             exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        methods.append(txt(name_node))
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _java_extract_params(node.child_by_field_name("parameters")),
            )
        )
        if _java_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_field(self, node: Node, properties: list[str], exports: list[dict]) -> None:
        for decl in find_children(node, "variable_declarator"):
            nn = decl.child_by_field_name("name")
            if nn is not None:
                properties.append(txt(nn))
                if _java_has_modifier(node, "public"):
                    exports.append(make_export(txt(nn), node.start_point[0] + 1))

    def _invocation_name(self, node: Node) -> str | None:
        nn = node.child_by_field_name("name")
        if nn is None:
            return None
        obj = node.child_by_field_name("object")
        if obj is not None:
            return f"{txt(obj)}.{txt(nn)}"
        return txt(nn)

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type in ("method_declaration", "constructor_declaration"):
                nn = node.child_by_field_name("name")
                if nn is not None:
                    stack.append(txt(nn))
                    pushed = True
            if node.type == "method_invocation" and stack:
                callee = self._invocation_name(node)
                if callee:
                    entries.append(_cg(stack[-1], callee, node.start_point[0] + 1))
            if node.type == "object_creation_expression" and stack:
                type_node = node.child_by_field_name("type")
                if type_node is not None:
                    entries.append(_cg(stack[-1], f"new {txt(type_node)}", node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# Kotlin
# ===========================================================================


def _kt_visibility(decl_node: Node) -> str | None:
    modifiers = find_child(decl_node, "modifiers")
    if modifiers is None:
        return None
    visibility = find_child(modifiers, "visibility_modifier")
    return txt(visibility) if visibility is not None else None


def _kt_is_exported(decl_node: Node) -> bool:
    visibility = _kt_visibility(decl_node)
    return visibility is None or visibility != "private"


def _kt_decl_name(decl_node: Node) -> str | None:
    # The pack's Kotlin grammar names functions/object-members with
    # `simple_identifier` and class/object types with `type_identifier`. Core's
    # grammar used plain `identifier`; accept all three so naming works on both.
    for child in decl_node.children:
        if child is not None and child.type in ("simple_identifier", "identifier", "type_identifier"):
            return txt(child)
    return None


def _kt_params(decl_node: Node) -> list[str]:
    params: list[str] = []
    value_params = find_child(decl_node, "function_value_parameters")
    if value_params is None:
        return params
    for param in find_children(value_params, "parameter"):
        ident = find_child(param, "simple_identifier") or find_child(param, "identifier")
        if ident is not None:
            params.append(txt(ident))
    return params


def _kt_return_type(decl_node: Node) -> str | None:
    saw_params = False
    children = decl_node.children
    for i, child in enumerate(children):
        if child is None:
            continue
        if child.type == "function_value_parameters":
            saw_params = True
            continue
        if saw_params and child.type == ":":
            for j in range(i + 1, len(children)):
                nxt = children[j]
                if nxt is not None and nxt.is_named:
                    return txt(nxt)
    return None


def _kt_property_name(prop_node: Node) -> str | None:
    var_decl = find_child(prop_node, "variable_declaration")
    if var_decl is None:
        return None
    ident = find_child(var_decl, "simple_identifier") or find_child(var_decl, "identifier")
    return txt(ident) if ident is not None else None


class KotlinExtractor:
    language_ids = ["kotlin"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        for node in root.children:
            if node is None:
                continue
            t = node.type
            if t == "package_header":
                continue
            if t == "import":
                self._extract_import(node, a.imports)
            elif t == "import_list":
                # The pack's grammar wraps imports in `import_list` >
                # `import_header`; core's exposed bare `import` nodes.
                for header in node.children:
                    if header is not None and header.type in ("import_header", "import"):
                        self._extract_import(header, a.imports)
            elif t == "function_declaration":
                self._top_level_function(node, a.functions, a.exports)
            elif t == "class_declaration":
                self._class_declaration(node, a.classes, a.functions, a.exports)
            elif t == "object_declaration":
                self._object_declaration(node, a.classes, a.functions, a.exports)
        return a

    def _collect_class_body(self, body: Node, methods: list[str], properties: list[str],
                            functions: list[dict], exports: list[dict]) -> None:
        for member in body.children:
            if member is None:
                continue
            if member.type == "function_declaration":
                name = _kt_decl_name(member)
                if not name:
                    continue
                methods.append(name)
                functions.append(
                    make_function(
                        name,
                        member.start_point[0] + 1,
                        member.end_point[0] + 1,
                        _kt_params(member),
                        _kt_return_type(member),
                    )
                )
                if _kt_is_exported(member):
                    exports.append(make_export(name, member.start_point[0] + 1))
            elif member.type == "property_declaration":
                name = _kt_property_name(member)
                if name:
                    properties.append(name)
                if name and _kt_is_exported(member):
                    exports.append(make_export(name, member.start_point[0] + 1))
            elif member.type == "object_declaration":
                name = _kt_decl_name(member)
                if name:
                    properties.append(name)

    def _collect_primary_constructor_props(self, decl_node: Node, properties: list[str]) -> None:
        primary = find_child(decl_node, "primary_constructor")
        if primary is None:
            return
        # Core's grammar nests parameters in a `class_parameters` node; the
        # pack's grammar lists `class_parameter` directly under the constructor.
        params_container = find_child(primary, "class_parameters") or primary
        for param in find_children(params_container, "class_parameter"):
            # A class_parameter is a property when it carries a `val`/`var`
            # keyword. Core's grammar exposes that keyword as a direct child;
            # the pack's grammar nests it under `binding_pattern_kind`.
            is_property = any(c is not None and c.type in ("val", "var") for c in param.children)
            if not is_property:
                bpk = find_child(param, "binding_pattern_kind")
                if bpk is not None:
                    is_property = any(c is not None and c.type in ("val", "var") for c in bpk.children)
            if not is_property:
                continue
            ident = find_child(param, "simple_identifier") or find_child(param, "identifier")
            if ident is not None:
                properties.append(txt(ident))

    def _top_level_function(self, decl_node: Node, functions: list[dict], exports: list[dict]) -> None:
        name = _kt_decl_name(decl_node)
        if not name:
            return
        functions.append(
            make_function(
                name,
                decl_node.start_point[0] + 1,
                decl_node.end_point[0] + 1,
                _kt_params(decl_node),
                _kt_return_type(decl_node),
            )
        )
        if _kt_is_exported(decl_node):
            exports.append(make_export(name, decl_node.start_point[0] + 1))

    def _class_declaration(self, decl_node: Node, classes: list[dict], functions: list[dict],
                           exports: list[dict]) -> None:
        name = _kt_decl_name(decl_node)
        if not name:
            return
        properties: list[str] = []
        methods: list[str] = []
        self._collect_primary_constructor_props(decl_node, properties)
        body = find_child(decl_node, "class_body")
        if body is not None:
            self._collect_class_body(body, methods, properties, functions, exports)
        classes.append(
            make_class(name, decl_node.start_point[0] + 1, decl_node.end_point[0] + 1, methods, properties)
        )
        if _kt_is_exported(decl_node):
            exports.append(make_export(name, decl_node.start_point[0] + 1))

    def _object_declaration(self, decl_node: Node, classes: list[dict], functions: list[dict],
                            exports: list[dict]) -> None:
        name = _kt_decl_name(decl_node)
        if not name:
            return
        properties: list[str] = []
        methods: list[str] = []
        body = find_child(decl_node, "class_body")
        if body is not None:
            self._collect_class_body(body, methods, properties, functions, exports)
        classes.append(
            make_class(name, decl_node.start_point[0] + 1, decl_node.end_point[0] + 1, methods, properties)
        )
        if _kt_is_exported(decl_node):
            exports.append(make_export(name, decl_node.start_point[0] + 1))

    def _extract_import(self, decl_node: Node, imports: list[dict]) -> None:
        # Core's grammar: `import` node with a `qualified_identifier` and
        # trailing `*` / `as identifier`. The pack's grammar: `import_header`
        # with an `identifier` (dotted, of `simple_identifier` parts), an
        # optional `wildcard_import` and `import_alias > type_identifier`.
        qualified = find_child(decl_node, "qualified_identifier")
        if qualified is not None:
            parts = [txt(i) for i in find_children(qualified, "identifier")]
        else:
            ident = find_child(decl_node, "identifier")
            if ident is None:
                return
            parts = [txt(c) for c in ident.children if c is not None and c.type in ("simple_identifier", "identifier")]
            if not parts:
                parts = [txt(ident)]
        if not parts:
            return
        source = ".".join(parts)
        specifier = parts[-1]

        saw_wildcard = find_child(decl_node, "wildcard_import") is not None
        # alias via `import_alias` (pack) ...
        alias = find_child(decl_node, "import_alias")
        if alias is not None:
            alias_id = (
                find_child(alias, "type_identifier")
                or find_child(alias, "simple_identifier")
                or find_child(alias, "identifier")
            )
            if alias_id is not None:
                specifier = txt(alias_id)
        else:
            # ... or `as identifier` siblings (core grammar)
            saw_as = False
            for child in decl_node.children:
                if child is None:
                    continue
                if child.type == "*":
                    saw_wildcard = True
                if child.type == "as":
                    saw_as = True
                elif saw_as and child.type in ("identifier", "type_identifier", "simple_identifier"):
                    specifier = txt(child)
                    saw_as = False
        if saw_wildcard:
            specifier = "*"
        imports.append(make_import(source, [specifier], decl_node.start_point[0] + 1))

    def _callee_name(self, call_node: Node) -> str | None:
        first = call_node.child(0)
        if first is None:
            return None
        if first.type in ("simple_identifier", "identifier"):
            return txt(first)
        if first.type == "navigation_expression":
            # The method name is the last identifier reachable in the
            # navigation chain. Core flattened identifiers directly under the
            # navigation_expression; the pack nests them in `navigation_suffix`.
            last_identifier: str | None = None
            for child in first.children:
                if child is None:
                    continue
                if child.type in ("simple_identifier", "identifier"):
                    last_identifier = txt(child)
                elif child.type == "navigation_suffix":
                    sid = find_child(child, "simple_identifier") or find_child(child, "identifier")
                    if sid is not None:
                        last_identifier = txt(sid)
            return last_identifier
        return None

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type == "function_declaration":
                name = _kt_decl_name(node)
                if name:
                    stack.append(name)
                    pushed = True
            if node.type == "call_expression" and stack:
                callee = self._callee_name(node)
                if callee:
                    entries.append(_cg(stack[-1], callee, node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# C#
# ===========================================================================


def _cs_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for param in find_children(params_node, "parameter"):
        nn = param.child_by_field_name("name")
        if nn is not None:
            params.append(txt(nn))
    return params


def _cs_has_modifier(node: Node, modifier: str) -> bool:
    for mod in find_children(node, "modifier"):
        for child in mod.children:
            if child is not None and txt(child) == modifier:
                return True
    return False


def _cs_using_source(node: Node) -> str | None:
    has_equals = find_child(node, "=") is not None
    if has_equals:
        qualified_name = find_child(node, "qualified_name")
        return txt(qualified_name) if qualified_name is not None else None
    qualified_name = find_child(node, "qualified_name")
    if qualified_name is not None:
        return txt(qualified_name)
    identifier = find_child(node, "identifier")
    return txt(identifier) if identifier is not None else None


class CSharpExtractor:
    language_ids = ["csharp"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        self._walk_top_level(root, a)
        return a

    def _walk_top_level(self, node: Node, a: StructuralAnalysis) -> None:
        for child in node.children:
            if child is None:
                continue
            t = child.type
            if t == "using_directive":
                self._extract_using(child, a.imports)
            elif t == "namespace_declaration":
                self._walk_namespace_body(child, a)
            elif t == "file_scoped_namespace_declaration":
                continue
            elif t == "class_declaration":
                self._extract_class(child, a.functions, a.classes, a.exports)
            elif t == "interface_declaration":
                self._extract_interface(child, a.functions, a.classes, a.exports)

    def _walk_namespace_body(self, ns_node: Node, a: StructuralAnalysis) -> None:
        body = ns_node.child_by_field_name("body")
        if body is None:
            return
        for child in body.children:
            if child is None:
                continue
            t = child.type
            if t == "class_declaration":
                self._extract_class(child, a.functions, a.classes, a.exports)
            elif t == "interface_declaration":
                self._extract_interface(child, a.functions, a.classes, a.exports)
            elif t == "namespace_declaration":
                self._walk_namespace_body(child, a)

    def _extract_using(self, node: Node, imports: list[dict]) -> None:
        source = _cs_using_source(node)
        if not source:
            return
        imports.append(make_import(source, [_last_component(source)], node.start_point[0] + 1))

    def _extract_class(self, node: Node, functions: list[dict], classes: list[dict],
                       exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        methods: list[str] = []
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None:
            self._class_body(body, methods, properties, functions, exports)
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )
        if _cs_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_interface(self, node: Node, functions: list[dict], classes: list[dict],
                           exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        methods: list[str] = []
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None:
            for method_node in find_children(body, "method_declaration"):
                mn = method_node.child_by_field_name("name")
                if mn is not None:
                    methods.append(txt(mn))
            for prop_node in find_children(body, "property_declaration"):
                pn = prop_node.child_by_field_name("name")
                if pn is not None:
                    properties.append(txt(pn))
        classes.append(
            make_class(txt(name_node), node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )
        if _cs_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _class_body(self, body: Node, methods: list[str], properties: list[str],
                    functions: list[dict], exports: list[dict]) -> None:
        for child in body.children:
            if child is None:
                continue
            t = child.type
            if t == "method_declaration":
                self._extract_method(child, methods, functions, exports)
            elif t == "constructor_declaration":
                self._extract_constructor(child, methods, functions, exports)
            elif t == "property_declaration":
                self._extract_property(child, properties, exports)
            elif t == "field_declaration":
                self._extract_field(child, properties, exports)

    def _extract_method(self, node: Node, methods: list[str], functions: list[dict],
                        exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        returns = node.child_by_field_name("returns")
        methods.append(txt(name_node))
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _cs_extract_params(node.child_by_field_name("parameters")),
                txt(returns) if returns is not None else None,
            )
        )
        if _cs_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_constructor(self, node: Node, methods: list[str], functions: list[dict],
                             exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        methods.append(txt(name_node))
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _cs_extract_params(node.child_by_field_name("parameters")),
            )
        )
        if _cs_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_property(self, node: Node, properties: list[str], exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        properties.append(txt(name_node))
        if _cs_has_modifier(node, "public"):
            exports.append(make_export(txt(name_node), node.start_point[0] + 1))

    def _extract_field(self, node: Node, properties: list[str], exports: list[dict]) -> None:
        var_decl = find_child(node, "variable_declaration")
        if var_decl is None:
            return
        for decl in find_children(var_decl, "variable_declarator"):
            nn = find_child(decl, "identifier")
            if nn is not None:
                properties.append(txt(nn))
                if _cs_has_modifier(node, "public"):
                    exports.append(make_export(txt(nn), node.start_point[0] + 1))

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type in ("method_declaration", "constructor_declaration"):
                nn = node.child_by_field_name("name")
                if nn is not None:
                    stack.append(txt(nn))
                    pushed = True
            if node.type == "invocation_expression" and stack:
                func_node = node.child_by_field_name("function")
                if func_node is not None:
                    entries.append(_cg(stack[-1], txt(func_node), node.start_point[0] + 1))
            if node.type == "object_creation_expression" and stack:
                type_node = find_child(node, "identifier") or find_child(node, "generic_name")
                if type_node is not None:
                    entries.append(_cg(stack[-1], f"new {txt(type_node)}", node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# PHP
# ===========================================================================


def _php_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for param in find_children(params_node, "simple_parameter"):
        var_name = find_child(param, "variable_name")
        if var_name is not None:
            params.append(txt(var_name))
    return params


def _php_return_type(node: Node) -> str | None:
    found_colon = False
    for child in node.children:
        if child is None:
            continue
        if child.type == ":" and txt(child) == ":":
            found_colon = True
            continue
        if found_colon:
            if child.type in ("primitive_type", "named_type", "optional_type", "union_type"):
                return txt(child)
    return None


def _php_use_name(clause: Node, prefix: str) -> str:
    qualified_name = find_child(clause, "qualified_name")
    if qualified_name is not None:
        return txt(qualified_name)
    name_node = find_child(clause, "name")
    if name_node is not None and prefix:
        return prefix + "\\" + txt(name_node)
    if name_node is not None:
        return txt(name_node)
    return txt(clause)


class PhpExtractor:
    language_ids = ["php"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        self._walk_statements(root, a)
        return a

    def _walk_statements(self, parent: Node, a: StructuralAnalysis) -> None:
        for node in parent.children:
            if node is None:
                continue
            t = node.type
            if t == "function_definition":
                self._extract_function(node, a.functions)
                a.exports.append(make_export(self._name(node), node.start_point[0] + 1))
            elif t == "class_declaration":
                self._extract_class(node, a.classes, a.functions)
                a.exports.append(make_export(self._name(node), node.start_point[0] + 1))
            elif t == "interface_declaration":
                self._extract_interface(node, a.classes)
                a.exports.append(make_export(self._name(node), node.start_point[0] + 1))
            elif t == "namespace_use_declaration":
                self._extract_use_declaration(node, a.imports)
            elif t == "namespace_definition":
                body = find_child(node, "compound_statement")
                if body is not None:
                    self._walk_statements(body, a)

    def _name(self, node: Node) -> str:
        nn = find_child(node, "name")
        return txt(nn) if nn is not None else ""

    def _extract_function(self, node: Node, functions: list[dict]) -> None:
        name_node = find_child(node, "name")
        if name_node is None:
            return
        params_node = find_child(node, "formal_parameters")
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _php_extract_params(params_node),
                _php_return_type(node),
            )
        )

    def _extract_class(self, node: Node, classes: list[dict], functions: list[dict]) -> None:
        name = self._name(node)
        if not name:
            return
        methods: list[str] = []
        properties: list[str] = []
        decl_list = find_child(node, "declaration_list")
        if decl_list is not None:
            self._extract_declaration_list(decl_list, methods, properties, functions)
        classes.append(
            make_class(name, node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )

    def _extract_interface(self, node: Node, classes: list[dict]) -> None:
        name = self._name(node)
        if not name:
            return
        methods: list[str] = []
        decl_list = find_child(node, "declaration_list")
        if decl_list is not None:
            for method_decl in find_children(decl_list, "method_declaration"):
                mn = find_child(method_decl, "name")
                if mn is not None:
                    methods.append(txt(mn))
        classes.append(
            make_class(name, node.start_point[0] + 1, node.end_point[0] + 1, methods, [])
        )

    def _extract_declaration_list(self, decl_list: Node, methods: list[str], properties: list[str],
                                  functions: list[dict]) -> None:
        for member in decl_list.children:
            if member is None:
                continue
            if member.type == "method_declaration":
                nn = find_child(member, "name")
                if nn is not None:
                    methods.append(txt(nn))
                    params_node = find_child(member, "formal_parameters")
                    functions.append(
                        make_function(
                            txt(nn),
                            member.start_point[0] + 1,
                            member.end_point[0] + 1,
                            _php_extract_params(params_node),
                            _php_return_type(member),
                        )
                    )
            elif member.type == "property_declaration":
                prop_element = find_child(member, "property_element")
                if prop_element is not None:
                    var_name = find_child(prop_element, "variable_name")
                    if var_name is not None:
                        dollar_child = find_child(var_name, "name")
                        if dollar_child is not None:
                            properties.append(txt(dollar_child))
                        else:
                            properties.append(txt(var_name).lstrip("$"))

    def _extract_use_declaration(self, node: Node, imports: list[dict]) -> None:
        use_group = find_child(node, "namespace_use_group")
        line = node.start_point[0] + 1
        if use_group is not None:
            ns_name = find_child(node, "namespace_name")
            prefix = txt(ns_name) if ns_name is not None else ""
            specifiers: list[str] = []
            for clause in find_children(use_group, "namespace_use_clause"):
                name = _php_use_name(clause, prefix)
                specifiers.append(_last_component(name, "\\"))
            source = prefix + "\\{" + ", ".join(specifiers) + "}" if prefix else ", ".join(specifiers)
            imports.append(make_import(source, specifiers, line))
            return
        for clause in find_children(node, "namespace_use_clause"):
            fqn = _php_use_name(clause, "")
            imports.append(make_import(fqn, [_last_component(fqn, "\\")], line))

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type in ("function_definition", "method_declaration"):
                nn = find_child(node, "name")
                if nn is not None:
                    stack.append(txt(nn))
                    pushed = True
            if stack:
                caller = stack[-1]
                if node.type == "function_call_expression":
                    nn = find_child(node, "name")
                    if nn is not None:
                        entries.append(_cg(caller, txt(nn), node.start_point[0] + 1))
                elif node.type == "member_call_expression":
                    nn = find_child(node, "name")
                    if nn is not None:
                        first_child = node.child(0)
                        receiver = txt(first_child) if first_child is not None else ""
                        callee = receiver + "->" + txt(nn) if receiver else txt(nn)
                        entries.append(_cg(caller, callee, node.start_point[0] + 1))
                elif node.type == "scoped_call_expression":
                    scope_node = node.child(0)
                    method_node = node.child(2)
                    if scope_node is not None and method_node is not None and method_node.type == "name":
                        entries.append(
                            _cg(caller, txt(scope_node) + "::" + txt(method_node), node.start_point[0] + 1)
                        )
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# Ruby
# ===========================================================================

_RUBY_IMPORT_METHODS = {"require", "require_relative"}
_RUBY_ATTR_METHODS = {"attr_accessor", "attr_reader", "attr_writer"}


def _ruby_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for child in params_node.children:
        if child is None:
            continue
        t = child.type
        if t == "identifier":
            params.append(txt(child))
        elif t == "optional_parameter":
            ident = child.child_by_field_name("name")
            if ident is not None:
                params.append(txt(ident))
        elif t == "splat_parameter":
            ident = child.child_by_field_name("name")
            if ident is not None:
                params.append("*" + txt(ident))
        elif t == "hash_splat_parameter":
            ident = child.child_by_field_name("name")
            if ident is not None:
                params.append("**" + txt(ident))
        elif t == "block_parameter":
            ident = child.child_by_field_name("name")
            if ident is not None:
                params.append("&" + txt(ident))
    return params


def _ruby_attr_properties(call_node: Node) -> list[str]:
    properties: list[str] = []
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return properties
    for child in args.children:
        if child is not None and child.type == "simple_symbol":
            properties.append(txt(child)[1:])
    return properties


def _ruby_string_content(node: Node) -> str:
    content = find_child(node, "string_content")
    if content is not None:
        return txt(content)
    s = txt(node)
    if s and s[0] in "'\"`":
        s = s[1:]
    if s and s[-1] in "'\"`":
        s = s[:-1]
    return s


class RubyExtractor:
    language_ids = ["ruby"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        for node in root.children:
            if node is None:
                continue
            t = node.type
            if t == "method":
                self._extract_method(node, a.functions)
                a.exports.append(make_export(self._field_name(node), node.start_point[0] + 1))
            elif t == "singleton_method":
                self._extract_singleton_method(node, a.functions)
                a.exports.append(make_export("self." + self._field_name(node), node.start_point[0] + 1))
            elif t == "class":
                self._extract_class(node, a.classes, a.functions)
                a.exports.append(make_export(self._field_name(node), node.start_point[0] + 1))
            elif t == "module":
                self._extract_module(node, a.classes, a.functions)
                a.exports.append(make_export(self._field_name(node), node.start_point[0] + 1))
            elif t == "call":
                self._extract_top_level_call(node, a.imports)
        return a

    def _field_name(self, node: Node) -> str:
        nn = node.child_by_field_name("name")
        return txt(nn) if nn is not None else ""

    def _extract_method(self, node: Node, functions: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        functions.append(
            make_function(
                txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _ruby_extract_params(node.child_by_field_name("parameters")),
            )
        )

    def _extract_singleton_method(self, node: Node, functions: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        functions.append(
            make_function(
                "self." + txt(name_node),
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _ruby_extract_params(node.child_by_field_name("parameters")),
            )
        )

    def _extract_class(self, node: Node, classes: list[dict], functions: list[dict]) -> None:
        name = self._field_name(node)
        if not name:
            return
        methods: list[str] = []
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None:
            self._extract_class_body(body, methods, properties, functions)
        classes.append(
            make_class(name, node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )

    def _extract_module(self, node: Node, classes: list[dict], functions: list[dict]) -> None:
        name = self._field_name(node)
        if not name:
            return
        methods: list[str] = []
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None:
            self._extract_class_body(body, methods, properties, functions)
        classes.append(
            make_class(name, node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )

    def _extract_class_body(self, body: Node, methods: list[str], properties: list[str],
                            functions: list[dict]) -> None:
        for member in body.children:
            if member is None:
                continue
            if member.type == "method":
                nn = member.child_by_field_name("name")
                if nn is not None:
                    methods.append(txt(nn))
                    self._extract_method(member, functions)
            elif member.type == "singleton_method":
                nn = member.child_by_field_name("name")
                if nn is not None:
                    methods.append("self." + txt(nn))
                    self._extract_singleton_method(member, functions)
            elif member.type == "call":
                mn = member.child_by_field_name("method")
                if mn is not None and txt(mn) in _RUBY_ATTR_METHODS:
                    properties.extend(_ruby_attr_properties(member))

    def _extract_top_level_call(self, node: Node, imports: list[dict]) -> None:
        method_node = node.child_by_field_name("method")
        if method_node is None:
            return
        if txt(method_node) in _RUBY_IMPORT_METHODS:
            args = node.child_by_field_name("arguments")
            if args is None:
                return
            first_arg = find_child(args, "string")
            if first_arg is not None:
                source = _ruby_string_content(first_arg)
                imports.append(make_import(source, [source], node.start_point[0] + 1))

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type == "method":
                nn = node.child_by_field_name("name")
                if nn is not None:
                    stack.append(txt(nn))
                    pushed = True
            elif node.type == "singleton_method":
                nn = node.child_by_field_name("name")
                if nn is not None:
                    stack.append("self." + txt(nn))
                    pushed = True
            if node.type == "call":
                method_node = node.child_by_field_name("method")
                if method_node is not None and stack:
                    method_name = txt(method_node)
                    if method_name not in _RUBY_IMPORT_METHODS and method_name not in _RUBY_ATTR_METHODS:
                        receiver_node = node.child_by_field_name("receiver")
                        callee = txt(receiver_node) + "." + method_name if receiver_node is not None else method_name
                        entries.append(_cg(stack[-1], callee, node.start_point[0] + 1))
            if (
                node.type == "identifier"
                and node.parent is not None
                and node.parent.type == "body_statement"
                and stack
            ):
                entries.append(_cg(stack[-1], txt(node), node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ===========================================================================
# C / C++
# ===========================================================================


def _cpp_unwrap_declarator_name(node: Node) -> str | None:
    if node.type in ("identifier", "field_identifier"):
        return txt(node)
    inner = node.child_by_field_name("declarator")
    if inner is not None:
        return _cpp_unwrap_declarator_name(inner)
    id_node = find_child(node, "identifier") or find_child(node, "field_identifier")
    return txt(id_node) if id_node is not None else None


def _cpp_func_decl_name(func_decl: Node) -> dict | None:
    decl_node = func_decl.child_by_field_name("declarator")
    if decl_node is None:
        return None
    if decl_node.type in ("identifier", "field_identifier"):
        return {"name": txt(decl_node), "qualifier": None}
    if decl_node.type == "qualified_identifier":
        name_node = decl_node.child_by_field_name("name")
        ns_node = find_child(decl_node, "namespace_identifier")
        return {
            "name": txt(name_node) if name_node is not None else txt(decl_node),
            "qualifier": txt(ns_node) if ns_node is not None else None,
        }
    return {"name": txt(decl_node), "qualifier": None}


def _cpp_extract_params(params_node: Node | None) -> list[str]:
    if params_node is None:
        return []
    params: list[str] = []
    for decl in find_children(params_node, "parameter_declaration"):
        decl_node = decl.child_by_field_name("declarator")
        if decl_node is not None:
            name = _cpp_unwrap_declarator_name(decl_node)
            if name:
                params.append(name)
    return params


def _cpp_is_static(node: Node) -> bool:
    storage = find_child(node, "storage_class_specifier")
    return storage is not None and txt(storage) == "static"


class CppExtractor:
    language_ids = ["cpp", "c"]

    def extract_structure(self, root: Node) -> StructuralAnalysis:
        a = StructuralAnalysis()
        methods_by_class: dict[str, list[str]] = {}
        self._walk_top_level(root, a, methods_by_class)
        for cls in a.classes:
            methods = methods_by_class.get(cls["name"])
            if methods:
                for m in methods:
                    if m not in cls["methods"]:
                        cls["methods"].append(m)
        return a

    def _walk_top_level(self, parent_node: Node, a: StructuralAnalysis,
                        methods_by_class: dict[str, list[str]]) -> None:
        for node in parent_node.children:
            if node is None:
                continue
            t = node.type
            if t == "preproc_include":
                self._extract_include(node, a.imports)
            elif t == "class_specifier":
                self._extract_class_or_struct(node, "class", a.classes, a.functions, a.exports)
            elif t == "struct_specifier":
                self._extract_class_or_struct(node, "struct", a.classes, a.functions, a.exports)
            elif t == "function_definition":
                self._extract_function_def(node, a.functions, a.exports, methods_by_class)
            elif t == "namespace_definition":
                body = find_child(node, "declaration_list")
                if body is not None:
                    self._walk_top_level(body, a, methods_by_class)
            elif t == "declaration":
                inner_class = find_child(node, "class_specifier")
                if inner_class is not None:
                    self._extract_class_or_struct(inner_class, "class", a.classes, a.functions, a.exports)
                inner_struct = find_child(node, "struct_specifier")
                if inner_struct is not None:
                    self._extract_class_or_struct(inner_struct, "struct", a.classes, a.functions, a.exports)

    def _extract_function_name(self, node: Node) -> str | None:
        decl_node = node.child_by_field_name("declarator")
        if decl_node is None or decl_node.type != "function_declarator":
            return None
        info = _cpp_func_decl_name(decl_node)
        return info["name"] if info else None

    def _extract_include(self, node: Node, imports: list[dict]) -> None:
        path_node = node.child_by_field_name("path")
        if path_node is None:
            return
        if path_node.type == "system_lib_string":
            source = txt(path_node).strip("<>")
        elif path_node.type == "string_literal":
            content = find_child(path_node, "string_content")
            source = txt(content) if content is not None else txt(path_node).strip('"')
        else:
            source = txt(path_node)
        imports.append(make_import(source, [source], node.start_point[0] + 1))

    def _extract_class_or_struct(self, node: Node, kind: str, classes: list[dict],
                                 functions: list[dict], exports: list[dict]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = txt(name_node)
        methods: list[str] = []
        properties: list[str] = []
        body = node.child_by_field_name("body")
        if body is not None and body.type == "field_declaration_list":
            current_access = "public" if kind == "struct" else "private"
            for member in body.children:
                if member is None:
                    continue
                if member.type == "access_specifier":
                    spec_child = member.child(0)
                    if spec_child is not None:
                        current_access = txt(spec_child)
                    continue
                if member.type == "field_declaration":
                    decl_node = member.child_by_field_name("declarator")
                    if decl_node is not None and decl_node.type == "function_declarator":
                        info = _cpp_func_decl_name(decl_node)
                        if info:
                            methods.append(info["name"])
                            if current_access == "public":
                                exports.append(make_export(info["name"], member.start_point[0] + 1))
                    elif decl_node is not None:
                        name = _cpp_unwrap_declarator_name(decl_node)
                        if name:
                            properties.append(name)
                if member.type == "function_definition":
                    func_decl = member.child_by_field_name("declarator")
                    if func_decl is not None and func_decl.type == "function_declarator":
                        info = _cpp_func_decl_name(func_decl)
                        if info:
                            methods.append(info["name"])
                            params_node = func_decl.child_by_field_name("parameters")
                            rt = member.child_by_field_name("type")
                            functions.append(
                                make_function(
                                    info["name"],
                                    member.start_point[0] + 1,
                                    member.end_point[0] + 1,
                                    _cpp_extract_params(params_node),
                                    txt(rt) if rt is not None else None,
                                )
                            )
                            if current_access == "public":
                                exports.append(make_export(info["name"], member.start_point[0] + 1))
        classes.append(
            make_class(class_name, node.start_point[0] + 1, node.end_point[0] + 1, methods, properties)
        )
        exports.append(make_export(class_name, node.start_point[0] + 1))

    def _extract_function_def(self, node: Node, functions: list[dict], exports: list[dict],
                              methods_by_class: dict[str, list[str]]) -> None:
        func_decl = node.child_by_field_name("declarator")
        if func_decl is None or func_decl.type != "function_declarator":
            return
        info = _cpp_func_decl_name(func_decl)
        if info is None:
            return
        params_node = func_decl.child_by_field_name("parameters")
        rt = node.child_by_field_name("type")
        functions.append(
            make_function(
                info["name"],
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                _cpp_extract_params(params_node),
                txt(rt) if rt is not None else None,
            )
        )
        if info["qualifier"]:
            methods_by_class.setdefault(info["qualifier"], []).append(info["name"])
        if not _cpp_is_static(node):
            exports.append(make_export(info["name"], node.start_point[0] + 1))

    def _callee_name(self, call_node: Node) -> str | None:
        func_node = call_node.child(0)
        if func_node is None:
            return None
        if func_node.type == "identifier":
            return txt(func_node)
        if func_node.type == "field_expression":
            field = func_node.child_by_field_name("field")
            return txt(field) if field is not None else txt(func_node)
        if func_node.type == "qualified_identifier":
            return txt(func_node)
        return txt(func_node)

    def extract_call_graph(self, root: Node) -> list[dict]:
        entries: list[dict] = []
        stack: list[str] = []

        def walk(node: Node) -> None:
            pushed = False
            if node.type == "function_definition":
                name = self._extract_function_name(node)
                if name:
                    stack.append(name)
                    pushed = True
            if node.type == "call_expression" and stack:
                callee = self._callee_name(node)
                if callee:
                    entries.append(_cg(stack[-1], callee, node.start_point[0] + 1))
            for child in node.children:
                if child is not None:
                    walk(child)
            if pushed:
                stack.pop()

        walk(root)
        return entries


# ---------------------------------------------------------------------------
# Extractor registry (language id -> extractor instance)
# ---------------------------------------------------------------------------

_BUILTIN = [
    TypeScriptExtractor(),
    PythonExtractor(),
    GoExtractor(),
    RustExtractor(),
    JavaExtractor(),
    RubyExtractor(),
    PhpExtractor(),
    CppExtractor(),
    CSharpExtractor(),
    KotlinExtractor(),
]

EXTRACTORS_BY_ID: dict[str, object] = {}
for _ex in _BUILTIN:
    for _id in _ex.language_ids:  # type: ignore[attr-defined]
        EXTRACTORS_BY_ID[_id] = _ex


def get_extractor(language_id: str):
    """Return the extractor for a tree-sitter language id, or None.

    ``tsx`` maps to the TypeScript extractor (same logic), mirroring core.
    """
    key = "typescript" if language_id == "tsx" else language_id
    return EXTRACTORS_BY_ID.get(key)
