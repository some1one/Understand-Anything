"""Dart tree-sitter extractor.

Port of ``plugins/extractors/dart-extractor.ts`` adapted to the Python
``tree_sitter`` API.
"""

from __future__ import annotations

from typing import Any

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    get_string_value,
    node_text,
)


def _is_exported(name: str) -> bool:
    """Whether a Dart name is exported (anything not prefixed with ``_``)."""
    return not name.startswith("_")


def _extract_function_name(sig: Any) -> str | None:
    """Extract the identifier name from a ``function_signature``-like node."""
    id_node = find_child(sig, "identifier")
    return node_text(id_node) if id_node else None


def _extract_param_name(param_node: Any) -> str | None:
    """Extract the user-visible name from a ``formal_parameter`` node.

    Handles regular ``Type name`` plus ``this.field`` / ``super.field`` shapes,
    in which case the last nested identifier is the field name.
    """
    # Direct identifier child wins (regular `Type name` parameter).
    direct = find_child(param_node, "identifier")
    if direct:
        return node_text(direct)

    # Nested wrappers — pick the last identifier we can find inside.
    for child in param_node.children:
        if not child:
            continue
        if child.type == "constructor_param" or child.type == "super_formal_parameter":
            last: str | None = None
            for inner in child.children:
                if inner and inner.type == "identifier":
                    last = node_text(inner)
            if last:
                return last
    return None


def _extract_params(sig: Any) -> list[str]:
    """Extract parameter names from a ``formal_parameter_list``.

    Walks both required parameters and the ``optional_formal_parameters``
    wrapper (used for both positional ``[...]`` and named ``{...}`` params).
    """
    params: list[str] = []
    list_node = find_child(sig, "formal_parameter_list")
    if not list_node:
        return params
    for child in list_node.children:
        if not child:
            continue
        if child.type == "formal_parameter":
            name = _extract_param_name(child)
            if name:
                params.append(name)
        elif child.type == "optional_formal_parameters":
            # Walk one level deeper — children are again `formal_parameter`.
            for sub in find_children(child, "formal_parameter"):
                name = _extract_param_name(sub)
                if name:
                    params.append(name)
    return params


def _extract_return_type(sig: Any) -> str | None:
    """Extract the return type from a ``function_signature``.

    The return type is the sequence of NAMED children that appear before the
    function name (``identifier``), the parameter list, or the function's own
    generic parameters (``type_parameters``).
    """
    parts: list[str] = []
    for child in sig.children:
        if not child or not child.is_named:
            continue
        if (
            child.type == "identifier"
            or child.type == "formal_parameter_list"
            or child.type == "type_parameters"
        ):
            # Reached the function NAME, the parameter list, or the function's
            # own generics. Anything before this point was the return type.
            break
        parts.append(node_text(child))
    return "".join(parts) if len(parts) > 0 else None


def _push_method(
    decl_node: Any,
    sig: Any,
    name: str,
    methods: list[str],
    functions: list[dict[str, Any]],
    exports: list[dict[str, Any]],
) -> None:
    """Push a method/function entry into ``methods``, ``functions``, exports."""
    methods.append(name)
    functions.append(
        {
            "name": name,
            "lineRange": [decl_node.start_point[0] + 1, decl_node.end_point[0] + 1],
            "params": _extract_params(sig),
            "returnType": _extract_return_type(sig),
        }
    )
    if _is_exported(name):
        exports.append({"name": name, "lineNumber": decl_node.start_point[0] + 1})


def _uri_text(uri_node: Any) -> str | None:
    """Unwrap the string-literal text from a ``uri > string_literal`` node."""
    lit = find_child(uri_node, "string_literal")
    if not lit:
        return None
    return get_string_value(lit)


def _constructor_name(sig: Any) -> str | None:
    """Build a constructor's method-graph name from a signature node.

    One identifier -> unnamed constructor (``<Class>``); two identifiers ->
    named constructor (``<Class>.<named>``).
    """
    ids = find_children(sig, "identifier")
    if len(ids) == 0:
        return None
    if len(ids) == 1:
        return node_text(ids[0])
    return f"{node_text(ids[0])}.{node_text(ids[1])}"


def _collect_class_body(
    body: Any,
    methods: list[str],
    properties: list[str],
    functions: list[dict[str, Any]],
    exports: list[dict[str, Any]],
) -> None:
    """Walk a class/extension/enum body collecting methods and fields."""
    for member in body.children:
        if not member:
            continue

        if member.type == "method_signature":
            # Factory constructor lives inside method_signature.
            factory = find_child(member, "factory_constructor_signature")
            if factory:
                name = _constructor_name(factory)
                if name:
                    _push_method(member, factory, name, methods, functions, exports)
                continue
            # Getter (`int get value`) — wrapped in method_signature.
            getter = find_child(member, "getter_signature")
            if getter:
                name = _extract_function_name(getter)
                if name:
                    _push_method(member, getter, name, methods, functions, exports)
                continue
            # Setter (`set value(int x)`) — wrapped in method_signature.
            setter = find_child(member, "setter_signature")
            if setter:
                name = _extract_function_name(setter)
                if name:
                    _push_method(member, setter, name, methods, functions, exports)
                continue
            # Concrete method: `method_signature > function_signature`.
            inner = find_child(member, "function_signature")
            if not inner:
                continue
            name = _extract_function_name(inner)
            if not name:
                continue
            _push_method(member, inner, name, methods, functions, exports)
        elif member.type == "declaration":
            # Regular constructor: `declaration > constructor_signature`.
            ctor = find_child(member, "constructor_signature")
            if ctor:
                name = _constructor_name(ctor)
                if name:
                    _push_method(member, ctor, name, methods, functions, exports)
                continue
            # Abstract getter (`int get area;`) — `declaration > getter_signature`.
            abs_getter = find_child(member, "getter_signature")
            if abs_getter:
                name = _extract_function_name(abs_getter)
                if name:
                    _push_method(member, abs_getter, name, methods, functions, exports)
                continue
            # Abstract setter (`set width(int w);`) — `declaration > setter_signature`.
            abs_setter = find_child(member, "setter_signature")
            if abs_setter:
                name = _extract_function_name(abs_setter)
                if name:
                    _push_method(member, abs_setter, name, methods, functions, exports)
                continue
            # Abstract method declarations appear as
            # `declaration > function_signature`.
            fn_sig = find_child(member, "function_signature")
            if fn_sig:
                name = _extract_function_name(fn_sig)
                if name:
                    _push_method(member, fn_sig, name, methods, functions, exports)
                continue
            # Field declaration — surface initialized_identifier names.
            list_node = find_child(member, "initialized_identifier_list")
            if not list_node:
                continue
            for init in find_children(list_node, "initialized_identifier"):
                id_node = find_child(init, "identifier")
                if id_node:
                    properties.append(node_text(id_node))


class DartExtractor:
    """Dart extractor for tree-sitter structural analysis + call graph.

    Mixin / extension / enum declarations are folded into ``classes[]`` because
    the shared schema has no first-class slot for them. Anonymous extensions
    surface as ``"on <TargetType>"`` so they aren't silently dropped.
    """

    language_ids: list[str] = ["dart"]

    def extract_structure(self, root_node: Any) -> dict[str, Any]:
        """Extract functions, classes, imports, and exports from the AST."""
        functions: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        imports: list[dict[str, Any]] = []
        exports: list[dict[str, Any]] = []

        for node in root_node.children:
            if not node:
                continue

            node_type = node.type
            if node_type == "function_signature":
                self._extract_top_level_function(node, functions, exports)
            elif node_type == "class_definition":
                self._extract_class_like_declaration(
                    node, "class_body", classes, functions, exports
                )
            elif node_type == "mixin_declaration":
                self._extract_class_like_declaration(
                    node, "class_body", classes, functions, exports
                )
            elif node_type == "extension_declaration":
                self._extract_extension_declaration(node, classes, functions, exports)
            elif node_type == "enum_declaration":
                self._extract_enum_declaration(node, classes, exports)
            elif node_type == "import_or_export":
                self._extract_import_or_export(node, imports, exports)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "exports": exports,
        }

    # ---- Private helpers ----

    def _extract_top_level_function(
        self,
        sig: Any,
        functions: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        """Extract a top-level ``function_signature``."""
        name = _extract_function_name(sig)
        if not name:
            return
        functions.append(
            {
                "name": name,
                "lineRange": [sig.start_point[0] + 1, sig.end_point[0] + 1],
                "params": _extract_params(sig),
                "returnType": _extract_return_type(sig),
            }
        )
        if _is_exported(name):
            exports.append({"name": name, "lineNumber": sig.start_point[0] + 1})

    def _extract_class_like_declaration(
        self,
        decl_node: Any,
        body_node_type: str,
        classes: list[dict[str, Any]],
        functions: list[dict[str, Any]],
        exports: list[dict[str, Any]],
        name_override: str | None = None,
    ) -> None:
        """Extract a class-like declaration using a ``class_body``-shaped body.

        Used by ``class_definition``, ``mixin_declaration``, and
        ``extension_declaration``. ``name_override`` is used by anonymous
        extensions, which have no name in source.
        """
        if name_override is not None:
            name = name_override
        else:
            name_node = find_child(decl_node, "identifier")
            if not name_node:
                return
            name = node_text(name_node)

        methods: list[str] = []
        properties: list[str] = []

        body = find_child(decl_node, body_node_type)
        if body:
            _collect_class_body(body, methods, properties, functions, exports)

        classes.append(
            {
                "name": name,
                "lineRange": [decl_node.start_point[0] + 1, decl_node.end_point[0] + 1],
                "methods": methods,
                "properties": properties,
            }
        )

        if _is_exported(name):
            exports.append({"name": name, "lineNumber": decl_node.start_point[0] + 1})

    def _extract_extension_declaration(
        self,
        decl_node: Any,
        classes: list[dict[str, Any]],
        functions: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        """Extract an ``extension_declaration`` (named or anonymous)."""
        # Named extension — _extract_class_like_declaration finds the identifier.
        id_node = find_child(decl_node, "identifier")
        if id_node:
            self._extract_class_like_declaration(
                decl_node,
                "extension_body",
                classes,
                functions,
                exports,
            )
            return

        # Anonymous extension — no `identifier` child. The on-type is the first
        # `type_identifier`. Name the entry "on <TargetType>".
        on_type = find_child(decl_node, "type_identifier")
        if not on_type:
            return
        self._extract_class_like_declaration(
            decl_node,
            "extension_body",
            classes,
            functions,
            exports,
            f"on {node_text(on_type)}",
        )

    def _extract_enum_declaration(
        self,
        decl_node: Any,
        classes: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        """Extract an ``enum_declaration``, surfacing constants as properties."""
        name_node = find_child(decl_node, "identifier")
        if not name_node:
            return
        name = node_text(name_node)

        properties: list[str] = []
        body = find_child(decl_node, "enum_body")
        if body:
            for k in find_children(body, "enum_constant"):
                id_node = find_child(k, "identifier")
                if id_node:
                    properties.append(node_text(id_node))

        classes.append(
            {
                "name": name,
                "lineRange": [decl_node.start_point[0] + 1, decl_node.end_point[0] + 1],
                "methods": [],
                "properties": properties,
            }
        )

        if _is_exported(name):
            exports.append({"name": name, "lineNumber": decl_node.start_point[0] + 1})

    def _extract_import_or_export(
        self,
        decl_node: Any,
        imports: list[dict[str, Any]],
        exports: list[dict[str, Any]],
    ) -> None:
        """Dispatch an ``import_or_export`` node to import/export extraction."""
        lib_import = find_child(decl_node, "library_import")
        if lib_import:
            self._extract_library_import(lib_import, imports)
            return
        lib_export = find_child(decl_node, "library_export")
        if lib_export:
            self._extract_library_export(lib_export, decl_node, exports)

    def _extract_library_import(
        self,
        lib_import: Any,
        imports: list[dict[str, Any]],
    ) -> None:
        """Extract a ``library_import`` into the imports array."""
        spec = find_child(lib_import, "import_specification")
        if not spec:
            return

        configurable = find_child(spec, "configurable_uri")
        uri = find_child(configurable, "uri") if configurable else None
        if not uri:
            return
        source = _uri_text(uri)
        if not source:
            return

        specifiers: list[str] = []

        # Combinators: `show Bar, Baz` (names are specifiers) vs `hide Qux`
        # (excluded — skip).
        combinators = find_children(spec, "combinator")
        for c in combinators:
            # Inspect the first child to determine show vs hide. The keyword is
            # an unnamed token; use children[0] not named children.
            first = c.children[0] if c.children else None
            if first and first.type == "hide":
                continue
            for id_node in find_children(c, "identifier"):
                specifiers.append(node_text(id_node))

        # `as Foo` → direct `identifier` child of import_specification. Only
        # treat as alias when there were no show/hide specifiers.
        as_id = find_child(spec, "identifier")
        if as_id and len(specifiers) == 0:
            specifiers.append(node_text(as_id))

        imports.append(
            {
                "source": source,
                "specifiers": specifiers,
                "lineNumber": lib_import.start_point[0] + 1,
            }
        )

    def _extract_library_export(
        self,
        lib_export: Any,
        outer_node: Any,
        exports: list[dict[str, Any]],
    ) -> None:
        """Extract an ``export`` directive's URI into the exports array.

        The line number uses ``outer_node`` because ``library_export`` may
        start one child deeper than the ``export`` keyword.
        """
        configurable = find_child(lib_export, "configurable_uri")
        uri = find_child(configurable, "uri") if configurable else None
        if not uri:
            return
        source = _uri_text(uri)
        if not source:
            return
        exports.append(
            {
                "name": source,
                "lineNumber": outer_node.start_point[0] + 1,
            }
        )

    def extract_call_graph(self, root_node: Any) -> list[dict[str, Any]]:
        """Extract caller/callee edges from selector and constructor nodes."""
        entries: list[dict[str, Any]] = []
        function_stack: list[str] = []

        def walk_node(node: Any) -> None:
            if (
                node.type == "selector"
                and find_child(node, "argument_part")
                and len(function_stack) > 0
            ):
                # A call site: selector containing argument_part.
                callee = self._extract_callee_name(node)
                if callee:
                    entries.append(
                        {
                            "caller": function_stack[-1],
                            "callee": callee,
                            "lineNumber": node.start_point[0] + 1,
                        }
                    )

            # Constructor-call shapes that bypass the selector > argument_part
            # pattern: `const Foo(...)` and `new Foo(...)`. The callee is the
            # `type_identifier` child.
            if (
                node.type == "const_object_expression"
                or node.type == "new_expression"
            ) and len(function_stack) > 0:
                type_node = find_child(node, "type_identifier")
                if type_node:
                    entries.append(
                        {
                            "caller": function_stack[-1],
                            "callee": node_text(type_node),
                            "lineNumber": node.start_point[0] + 1,
                        }
                    )

            walk_siblings(node)

        def walk_siblings(parent: Any) -> None:
            pending_name: str | None = None

            for child in parent.children:
                if not child:
                    continue

                if child.type == "function_signature":
                    pending_name = _extract_function_name(child)
                    # Recurse into signature (no calls expected, but stay complete).
                    walk_siblings(child)
                elif child.type == "method_signature":
                    # method_signature wraps function/getter/setter/constructor/
                    # factory signatures; all carry the name as the first
                    # identifier child.
                    fn = (
                        find_child(child, "function_signature")
                        or find_child(child, "getter_signature")
                        or find_child(child, "setter_signature")
                    )
                    if fn:
                        pending_name = _extract_function_name(fn)
                    else:
                        ctor = find_child(
                            child, "constructor_signature"
                        ) or find_child(child, "factory_constructor_signature")
                        if ctor:
                            pending_name = _constructor_name(ctor)
                    walk_siblings(child)
                elif child.type == "function_body":
                    # Consume pending_name: push for the duration of this body.
                    pushed = pending_name is not None
                    if pending_name:
                        function_stack.append(pending_name)
                        pending_name = None
                    walk_node(child)
                    if pushed:
                        function_stack.pop()
                else:
                    # For every other node, do NOT clear pending_name —
                    # anonymous tokens appear between signature and body.
                    walk_node(child)

        walk_siblings(root_node)
        return entries

    def _extract_callee_name(self, call_selector: Any) -> str | None:
        """Find the callee name for a ``selector`` containing an argument_part.

        Looks at the preceding sibling: a bare ``identifier`` for plain calls,
        or a ``selector`` wrapping ``unconditional_assignable_selector`` for
        method calls. Sibling comparison uses ``start_byte`` (node identity is
        not stable across child accessors in the TS port).
        """
        parent = call_selector.parent
        if not parent:
            return None

        # Find this selector's index in the parent using start_byte (not ===).
        my_idx = -1
        for i, c in enumerate(parent.children):
            if c and c.start_byte == call_selector.start_byte:
                my_idx = i
                break
        if my_idx <= 0:
            return None

        prev = parent.children[my_idx - 1]
        if not prev:
            return None

        if prev.type == "identifier":
            return node_text(prev)

        if prev.type == "selector":
            # Method call shape: previous selector wraps
            # unconditional_assignable_selector.
            inner = find_child(prev, "unconditional_assignable_selector")
            if inner:
                # Pick the LAST identifier inside — that's the method name.
                last: str | None = None
                for child in inner.children:
                    if child and child.type == "identifier":
                        last = node_text(child)
                return last

        return None
