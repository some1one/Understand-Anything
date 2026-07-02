"""Tests for DartExtractor (ported from dart-extractor.test.ts)."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("dart")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.dart_extractor import DartExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = DartExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["dart"]


# ---- functions ----


def test_extracts_simple_top_level_function_with_params_and_return_type():
    root = _parse("int add(int a, int b) => a + b;\n")
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "add"
    assert result["functions"][0]["params"] == ["a", "b"]
    assert result["functions"][0]["returnType"] == "int"


def test_extracts_function_with_no_params_and_void_return_type():
    root = _parse("void noop() {}\n")
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "noop"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] == "void"


def test_extracts_async_function_with_generic_return_type():
    root = _parse('Future<String> fetch(String url) async { return ""; }\n')
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "fetch"
    assert result["functions"][0]["params"] == ["url"]
    assert result["functions"][0]["returnType"] == "Future<String>"


# ---- parameter kinds ----


def test_surfaces_optional_positional_parameters():
    root = _parse("void show([String? title, int count = 0]) {}\n")
    result = extractor.extract_structure(root)

    assert result["functions"][0]["params"] == ["title", "count"]


def test_surfaces_named_parameters_wrapped_in_braces():
    root = _parse("void show({String? title, int count = 0}) {}\n")
    result = extractor.extract_structure(root)

    assert result["functions"][0]["params"] == ["title", "count"]


def test_mixes_required_and_named_parameters_in_one_signature():
    root = _parse('String join(List<String> items, {String sep = ","}) => "";\n')
    result = extractor.extract_structure(root)

    assert result["functions"][0]["params"] == ["items", "sep"]


def test_extracts_this_field_constructor_parameters_as_the_field_name():
    root = _parse(
        """class Foo {
  int x;
  String y;
  Foo(this.x, this.y);
}
"""
    )
    result = extractor.extract_structure(root)

    ctor = next((f for f in result["functions"] if f["name"] == "Foo"), None)
    assert ctor is not None
    assert ctor["params"] == ["x", "y"]


# ---- classes ----


def test_extracts_a_class_with_fields_and_methods():
    root = _parse(
        """class Counter {
  int count = 0;
  String? label;
  void increment() { count++; }
  int get value => count;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Counter"
    assert "increment" in result["classes"][0]["methods"]
    assert "increment" in [f["name"] for f in result["functions"]]
    assert "count" in result["classes"][0]["properties"]
    assert "label" in result["classes"][0]["properties"]
    assert "value" in result["classes"][0]["methods"]


def test_extracts_an_empty_class():
    root = _parse("class Empty {}\n")
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Empty"
    assert result["classes"][0]["methods"] == []


def test_extracts_an_abstract_class_with_method_requirements():
    root = _parse(
        """abstract class Shape {
  double area();
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Shape"
    assert "area" in result["classes"][0]["methods"]


def test_extracts_a_class_with_extends_with_implements_clauses():
    root = _parse(
        """class Square extends Shape with Comparable<Square> implements Cloneable {
  double side;
  Square(this.side);
  double area() => side * side;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Square"
    assert "area" in result["classes"][0]["methods"]


def test_extracts_comma_list_field_declarations_as_separate_properties():
    root = _parse("class Foo { int a, b, c; }\n")
    result = extractor.extract_structure(root)

    assert result["classes"][0]["properties"] == ["a", "b", "c"]


# ---- getters and setters ----


def test_surfaces_a_concrete_getter_as_a_method():
    root = _parse(
        """class Counter {
  int _v = 0;
  int get value => _v;
}
"""
    )
    result = extractor.extract_structure(root)

    assert "value" in result["classes"][0]["methods"]
    assert "value" in [f["name"] for f in result["functions"]]


def test_surfaces_a_concrete_setter_as_a_method():
    root = _parse(
        """class Counter {
  int _v = 0;
  set value(int x) => _v = x;
}
"""
    )
    result = extractor.extract_structure(root)

    assert "value" in result["classes"][0]["methods"]
    assert "value" in [f["name"] for f in result["functions"]]


def test_surfaces_an_abstract_getter_as_a_method():
    root = _parse(
        """abstract class Shape {
  double get area;
}
"""
    )
    result = extractor.extract_structure(root)

    assert "area" in result["classes"][0]["methods"]


def test_surfaces_an_abstract_setter_as_a_method():
    root = _parse(
        """abstract class Box {
  set width(int w);
}
"""
    )
    result = extractor.extract_structure(root)

    assert "width" in result["classes"][0]["methods"]


def test_does_not_export_an_underscore_prefixed_getter():
    root = _parse(
        """class Counter {
  int _v = 0;
  int get _internal => _v;
  int get visible => _v;
}
"""
    )
    result = extractor.extract_structure(root)

    names = [e["name"] for e in result["exports"]]
    assert "visible" in names
    assert "_internal" not in names


# ---- constructors ----


def test_treats_an_unnamed_constructor_as_a_method_named_after_the_class():
    root = _parse(
        """class Foo {
  int x;
  Foo(this.x);
}
"""
    )
    result = extractor.extract_structure(root)

    assert "Foo" in result["classes"][0]["methods"]


def test_treats_a_named_constructor_as_class_named():
    root = _parse(
        """class Foo {
  int x;
  Foo.zero() : x = 0;
}
"""
    )
    result = extractor.extract_structure(root)

    assert "Foo.zero" in result["classes"][0]["methods"]


def test_treats_a_factory_named_constructor_as_class_named():
    root = _parse(
        """class Foo {
  int x;
  Foo(this.x);
  factory Foo.fromString(String s) => Foo(int.parse(s));
}
"""
    )
    result = extractor.extract_structure(root)

    assert "Foo.fromString" in result["classes"][0]["methods"]


# ---- mixins ----


def test_extracts_a_plain_mixin_as_a_class_like_entry():
    root = _parse(
        """mixin Walker {
  void walk() {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Walker"
    assert "walk" in result["classes"][0]["methods"]


def test_extracts_a_mixin_with_an_on_constraint():
    root = _parse(
        """mixin Runner on Walker {
  void run() {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert result["classes"][0]["name"] == "Runner"
    assert "run" in result["classes"][0]["methods"]


# ---- enums ----


def test_extracts_a_simple_enum_and_surfaces_its_constants_as_properties():
    root = _parse("enum Color { red, green, blue }\n")
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Color"
    assert result["classes"][0]["properties"] == ["red", "green", "blue"]


# ---- extensions ----


def test_extracts_a_named_extension_on_string():
    root = _parse(
        """extension StringX on String {
  String shout() => toUpperCase() + '!';
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "StringX"
    assert "shout" in result["classes"][0]["methods"]


def test_names_an_anonymous_extension_after_its_target_type():
    root = _parse(
        """extension on int {
  int squared() => this * this;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "on int"
    assert "squared" in result["classes"][0]["methods"]


# ---- imports ----


def test_extracts_a_package_import_with_no_specifiers():
    root = _parse("import 'package:flutter/material.dart';\n")
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "package:flutter/material.dart"
    assert result["imports"][0]["specifiers"] == []


def test_extracts_a_relative_import():
    root = _parse("import './foo.dart';\n")
    result = extractor.extract_structure(root)

    assert result["imports"][0]["source"] == "./foo.dart"


def test_extracts_a_show_clause_as_specifiers():
    root = _parse("import 'foo.dart' show Bar, Baz;\n")
    result = extractor.extract_structure(root)

    assert result["imports"][0]["source"] == "foo.dart"
    assert result["imports"][0]["specifiers"] == ["Bar", "Baz"]


def test_extracts_an_as_prefix_as_the_sole_specifier():
    root = _parse("import 'bar.dart' as b;\n")
    result = extractor.extract_structure(root)

    assert result["imports"][0]["source"] == "bar.dart"
    assert result["imports"][0]["specifiers"] == ["b"]


def test_does_not_include_hide_names_as_specifiers():
    root = _parse("import 'foo.dart' hide Qux;\n")
    result = extractor.extract_structure(root)

    assert result["imports"][0]["source"] == "foo.dart"
    assert result["imports"][0]["specifiers"] == []


def test_extracts_a_dart_sdk_import():
    root = _parse("import 'dart:io';\n")
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "dart:io"
    assert result["imports"][0]["specifiers"] == []


def test_preserves_declaration_order_across_multiple_imports():
    root = _parse(
        """import 'dart:io';
import 'package:flutter/material.dart';
import './foo.dart';
"""
    )
    result = extractor.extract_structure(root)

    assert [i["source"] for i in result["imports"]] == [
        "dart:io",
        "package:flutter/material.dart",
        "./foo.dart",
    ]


# ---- exports ----


def test_extracts_a_top_level_export_directive():
    root = _parse("export 'shared.dart';\n")
    result = extractor.extract_structure(root)

    shared_export = next(
        (e for e in result["exports"] if e["name"] == "shared.dart"), None
    )
    assert shared_export is not None


def test_extracts_a_show_clause_on_an_export_directive_uri_only():
    root = _parse("export 'shared.dart' show PublicApi;\n")
    result = extractor.extract_structure(root)

    shared_export = next(
        (e for e in result["exports"] if e["name"] == "shared.dart"), None
    )
    assert shared_export is not None


# ---- call graph ----


def test_attributes_a_top_level_call_to_its_enclosing_function():
    root = _parse(
        """int helper() => 1;
int caller() {
  return helper();
}
"""
    )
    entries = extractor.extract_call_graph(root)

    helper_call = next((e for e in entries if e["callee"] == "helper"), None)
    assert helper_call is not None
    assert helper_call["caller"] == "caller"


def test_attributes_a_method_call_to_its_enclosing_function():
    root = _parse(
        """void run() {
  "hi".toUpperCase();
}
"""
    )
    entries = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in entries]
    assert "toUpperCase" in callees


def test_returns_an_empty_array_when_there_are_no_calls():
    root = _parse("int a() => 1;\n")
    entries = extractor.extract_call_graph(root)
    assert entries == []


def test_records_a_const_foo_constructor_as_a_call_edge():
    root = _parse(
        """void main() {
  runApp(const MyApp());
}
"""
    )
    entries = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in entries]
    assert "runApp" in callees
    assert "MyApp" in callees
    my_app_call = next((e for e in entries if e["callee"] == "MyApp"), None)
    assert my_app_call["caller"] == "main"


def test_records_a_new_foo_constructor_as_a_call_edge():
    root = _parse(
        """void main() {
  var x = new Counter(1);
}
"""
    )
    entries = extractor.extract_call_graph(root)

    counter_call = next((e for e in entries if e["callee"] == "Counter"), None)
    assert counter_call is not None
    assert counter_call["caller"] == "main"


def test_attributes_calls_inside_a_getter_body_to_the_getter():
    root = _parse(
        """class C {
  int _v = 0;
  int get value {
    return helper();
  }
}
"""
    )
    entries = extractor.extract_call_graph(root)

    helper_call = next((e for e in entries if e["callee"] == "helper"), None)
    assert helper_call is not None
    assert helper_call["caller"] == "value"


def test_attributes_calls_inside_a_setter_body_to_the_setter():
    root = _parse(
        """class C {
  int _v = 0;
  set value(int x) {
    _v = clamp(x);
  }
}
"""
    )
    entries = extractor.extract_call_graph(root)

    clamp_call = next((e for e in entries if e["callee"] == "clamp"), None)
    assert clamp_call is not None
    assert clamp_call["caller"] == "value"


def test_attributes_calls_inside_a_constructor_body_to_the_constructor():
    root = _parse(
        """class Foo {
  int x;
  Foo(this.x) {
    validate(x);
  }
}
"""
    )
    entries = extractor.extract_call_graph(root)

    validate_call = next((e for e in entries if e["callee"] == "validate"), None)
    assert validate_call is not None
    assert validate_call["caller"] == "Foo"


def test_attributes_calls_inside_a_factory_constructor_body_to_class_named():
    root = _parse(
        """class Foo {
  int x;
  Foo(this.x);
  factory Foo.fromString(String s) {
    return Foo(int.parse(s));
  }
}
"""
    )
    entries = extractor.extract_call_graph(root)

    from_factory = [e for e in entries if e["caller"] == "Foo.fromString"]
    assert len(from_factory) > 0


# ---- visibility ----


def test_does_not_export_a_top_level_declaration_starting_with_underscore():
    root = _parse(
        """int _helper() => 1;
class _PrivateImpl {}
"""
    )
    result = extractor.extract_structure(root)

    names = [e["name"] for e in result["exports"]]
    assert "_helper" not in names
    assert "_PrivateImpl" not in names


def test_does_export_a_top_level_declaration_without_an_underscore_prefix():
    root = _parse(
        """int helper() => 1;
class Public {}
"""
    )
    result = extractor.extract_structure(root)

    names = [e["name"] for e in result["exports"]]
    assert "helper" in names
    assert "Public" in names


def test_does_not_export_class_members_starting_with_underscore():
    root = _parse(
        """class Counter {
  void _helper() {}
  void publicMethod() {}
}
"""
    )
    result = extractor.extract_structure(root)

    names = [e["name"] for e in result["exports"]]
    assert "publicMethod" in names
    assert "_helper" not in names
