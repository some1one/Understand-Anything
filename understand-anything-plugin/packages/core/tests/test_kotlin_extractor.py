"""Tests for KotlinExtractor. Port of kotlin-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("kotlin")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.kotlin_extractor import KotlinExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = KotlinExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["kotlin"]


# ---- functions ----


def test_extracts_a_simple_top_level_function_with_params_and_return_type():
    root = _parse("""fun add(a: Int, b: Int): Int = a + b\n""")
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "add"
    assert result["functions"][0]["params"] == ["a", "b"]
    assert result["functions"][0]["returnType"] == "Int"


def test_extracts_function_with_no_params_and_no_return_type():
    root = _parse("""fun noop() {}\n""")
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "noop"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] is None


def test_extracts_suspending_and_generic_functions():
    root = _parse(
        """suspend fun <T> fetch(id: String): T? {
    return null
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "fetch"
    assert result["functions"][0]["params"] == ["id"]
    assert result["functions"][0]["returnType"] == "T?"


def test_extracts_multiple_top_level_functions_in_declaration_order():
    root = _parse(
        """fun one() {}
fun two(x: Int): Int = x
fun three(): String = ""
"""
    )
    result = extractor.extract_structure(root)

    assert [f["name"] for f in result["functions"]] == ["one", "two", "three"]


# ---- classes ----


def test_extracts_a_class_with_primary_constructor_val_properties_and_methods():
    root = _parse(
        """class Foo(val bar: Int) {
    val baz: String = "hi"
    fun compute(): Int = bar * 2
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Foo"
    assert "bar" in result["classes"][0]["properties"]
    assert "baz" in result["classes"][0]["properties"]
    assert "compute" in result["classes"][0]["methods"]


def test_extracts_an_empty_class():
    root = _parse("""class Empty\n""")
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Empty"
    assert result["classes"][0]["methods"] == []
    assert result["classes"][0]["properties"] == []


def test_extracts_a_data_class_and_surfaces_constructor_parameters_as_properties():
    root = _parse("""data class Point(val x: Double, val y: Double)\n""")
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Point"
    assert result["classes"][0]["properties"] == ["x", "y"]


def test_extracts_class_methods_into_functions_as_well_as_methods():
    root = _parse(
        """class Foo {
    fun bar(): Int = 1
}
"""
    )
    result = extractor.extract_structure(root)

    assert "bar" in [f["name"] for f in result["functions"]]
    assert "bar" in result["classes"][0]["methods"]


# ---- interfaces ----


def test_extracts_an_interface_with_method_requirements_as_a_class_like_entry():
    root = _parse(
        """interface Greeter {
    fun greet(name: String): String
    fun farewell(): String
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Greeter"
    assert "greet" in result["classes"][0]["methods"]
    assert "farewell" in result["classes"][0]["methods"]


# ---- object declarations ----


def test_extracts_a_singleton_object_with_methods():
    root = _parse(
        """object Logger {
    fun info(msg: String) {}
    fun warn(msg: String) {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Logger"
    assert "info" in result["classes"][0]["methods"]
    assert "warn" in result["classes"][0]["methods"]


# ---- imports ----


def test_extracts_a_simple_dotted_import():
    root = _parse("""import kotlin.io.println\n""")
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "kotlin.io.println"
    assert result["imports"][0]["specifiers"] == ["println"]


def test_extracts_a_wildcard_import():
    root = _parse("""import kotlinx.coroutines.*\n""")
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "kotlinx.coroutines"
    assert result["imports"][0]["specifiers"] == ["*"]


def test_extracts_an_aliased_import():
    root = _parse("""import com.example.foo.Bar as Baz\n""")
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "com.example.foo.Bar"
    assert result["imports"][0]["specifiers"] == ["Baz"]


def test_extracts_multiple_imports_in_declaration_order():
    root = _parse(
        """package com.example.app

import kotlinx.coroutines.flow.Flow
import kotlin.io.println
import kotlinx.coroutines.*
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 3
    assert result["imports"][0]["source"] == "kotlinx.coroutines.flow.Flow"
    assert result["imports"][1]["source"] == "kotlin.io.println"
    assert result["imports"][2]["source"] == "kotlinx.coroutines"


# ---- exports / visibility ----


def test_treats_no_modifier_declarations_as_exported():
    root = _parse(
        """fun greet() {}
class Greeter {}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "greet" in export_names
    assert "Greeter" in export_names


def test_treats_public_internal_protected_as_exported():
    root = _parse(
        """public fun a() {}
internal class B {}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "a" in export_names
    assert "B" in export_names


def test_does_not_treat_private_declarations_as_exported():
    root = _parse(
        """private fun helper() {}
private class Internal {}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "helper" not in export_names
    assert "Internal" not in export_names


def test_exports_an_object_declaration_by_default():
    root = _parse("""object Logger {}\n""")
    result = extractor.extract_structure(root)

    assert "Logger" in [e["name"] for e in result["exports"]]


# ---- call graph ----


def test_extracts_a_call_from_one_function_to_another():
    root = _parse(
        """fun helper(): Int = 1

fun caller(): Int {
    return helper()
}
"""
    )
    entries = extractor.extract_call_graph(root)

    helper_call = next((e for e in entries if e["callee"] == "helper"), None)
    assert helper_call is not None
    assert helper_call["caller"] == "caller"


def test_extracts_method_calls_and_attributes_them_to_the_enclosing_function():
    root = _parse(
        """fun run() {
    val s = "hi".uppercase()
}
"""
    )
    entries = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in entries]
    assert "uppercase" in callees


def test_returns_an_empty_array_when_there_are_no_calls():
    root = _parse("""fun a(): Int = 1\n""")
    entries = extractor.extract_call_graph(root)
    assert entries == []
