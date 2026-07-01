"""Tests for RustExtractor. Port of rust-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("rust")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.rust_extractor import RustExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = RustExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["rust"]


# ---- Functions ----


def test_extracts_top_level_functions_with_params_and_return_types():
    root = _parse(
        """
pub fn check_port(port: u16) -> bool {
    port > 0
}

fn helper(name: String, count: i32) -> String {
    name.repeat(count)
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "check_port"
    assert result["functions"][0]["params"] == ["port"]
    assert result["functions"][0]["returnType"] == "bool"

    assert result["functions"][1]["name"] == "helper"
    assert result["functions"][1]["params"] == ["name", "count"]
    assert result["functions"][1]["returnType"] == "String"


def test_extracts_functions_with_no_params_and_no_return_type():
    root = _parse(
        """
fn noop() {
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "noop"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] is None


def test_reports_correct_line_ranges_for_multi_line_functions():
    root = _parse(
        """
fn multiline(
    a: i32,
    b: i32,
) -> i32 {
    let result = a + b;
    result
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 2
    assert result["functions"][0]["lineRange"][1] == 8


# ---- Methods (impl blocks) ----


def test_extracts_methods_from_impl_blocks_and_links_them_to_structs():
    root = _parse(
        """
pub struct Config {
    name: String,
    port: u16,
}

impl Config {
    pub fn new(name: String, port: u16) -> Self {
        Config { name, port }
    }

    fn validate(&self) -> bool {
        true
    }
}
"""
    )
    result = extractor.extract_structure(root)

    fn_names = [f["name"] for f in result["functions"]]
    assert "new" in fn_names
    assert "validate" in fn_names

    new_fn = next((f for f in result["functions"] if f["name"] == "new"), None)
    assert new_fn["params"] == ["name", "port"]
    assert new_fn["returnType"] == "Self"

    validate_fn = next((f for f in result["functions"] if f["name"] == "validate"), None)
    assert validate_fn["params"] == []
    assert validate_fn["returnType"] == "bool"

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Config"
    assert "new" in result["classes"][0]["methods"]
    assert "validate" in result["classes"][0]["methods"]


def test_handles_impl_blocks_for_enums():
    root = _parse(
        """
enum Status {
    Active,
    Inactive,
}

impl Status {
    fn is_active(&self) -> bool {
        true
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Status"
    assert "is_active" in result["classes"][0]["methods"]


# ---- Structs ----


def test_extracts_struct_with_fields():
    root = _parse(
        """
pub struct Config {
    name: String,
    port: u16,
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Config"
    assert result["classes"][0]["properties"] == ["name", "port"]
    assert result["classes"][0]["methods"] == []
    assert result["classes"][0]["lineRange"][0] == 2


def test_extracts_empty_struct_unit_struct():
    root = _parse(
        """
struct Empty;
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Empty"
    assert result["classes"][0]["properties"] == []
    assert result["classes"][0]["methods"] == []


# ---- Enums ----


def test_extracts_enum_with_variants_as_properties():
    root = _parse(
        """
enum Status {
    Active,
    Inactive,
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Status"
    assert result["classes"][0]["properties"] == ["Active", "Inactive"]
    assert result["classes"][0]["methods"] == []


def test_extracts_pub_enum():
    root = _parse(
        """
pub enum Direction {
    North,
    South,
    East,
    West,
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Direction"
    assert result["classes"][0]["properties"] == ["North", "South", "East", "West"]

    export_names = [e["name"] for e in result["exports"]]
    assert "Direction" in export_names


# ---- Traits ----


def test_extracts_trait_with_method_signatures():
    root = _parse(
        """
pub trait Validator {
    fn validate(&self) -> bool;
    fn name(&self) -> &str;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Validator"
    assert result["classes"][0]["methods"] == ["validate", "name"]
    assert result["classes"][0]["properties"] == []


def test_extracts_empty_trait():
    root = _parse(
        """
trait Marker {}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Marker"
    assert result["classes"][0]["methods"] == []


def test_exports_pub_traits():
    root = _parse(
        """
pub trait Serializable {
    fn serialize(&self) -> String;
}

trait Internal {
    fn process(&self);
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Serializable" in export_names
    assert "Internal" not in export_names


# ---- Imports ----


def test_extracts_scoped_identifier_imports():
    root = _parse(
        """
use std::collections::HashMap;
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "std::collections"
    assert result["imports"][0]["specifiers"] == ["HashMap"]


def test_extracts_scoped_use_list_imports():
    root = _parse(
        """
use std::io::{self, Read, Write};
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "std::io"
    assert result["imports"][0]["specifiers"] == ["self", "Read", "Write"]


def test_extracts_wildcard_imports():
    root = _parse(
        """
use std::prelude::*;
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "std::prelude"
    assert result["imports"][0]["specifiers"] == ["*"]


def test_extracts_simple_identifier_imports():
    root = _parse(
        """
use foo;
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "foo"
    assert result["imports"][0]["specifiers"] == ["foo"]


def test_extracts_crate_relative_imports():
    root = _parse(
        """
use crate::config::Settings;
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "crate::config"
    assert result["imports"][0]["specifiers"] == ["Settings"]


def test_reports_correct_import_line_numbers():
    root = _parse(
        """
use std::collections::HashMap;
use std::io::{self, Read};
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["lineNumber"] == 2
    assert result["imports"][1]["lineNumber"] == 3


# ---- Exports ----


def test_exports_pub_items_and_not_private_items():
    root = _parse(
        """
pub struct Config {
    name: String,
}

struct Internal {
    value: i32,
}

pub fn check_port(port: u16) -> bool {
    port > 0
}

fn helper() {}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Config" in export_names
    assert "check_port" in export_names
    assert "Internal" not in export_names
    assert "helper" not in export_names


def test_exports_pub_methods_inside_impl_blocks():
    root = _parse(
        """
pub struct Config {
    name: String,
}

impl Config {
    pub fn new(name: String) -> Self {
        Config { name }
    }

    fn validate(&self) -> bool {
        true
    }
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Config" in export_names
    assert "new" in export_names
    assert "validate" not in export_names


def test_reports_correct_export_line_numbers():
    root = _parse(
        """
pub struct Config {
    name: String,
}

pub fn check_port(port: u16) -> bool {
    port > 0
}
"""
    )
    result = extractor.extract_structure(root)

    config_export = next((e for e in result["exports"] if e["name"] == "Config"), None)
    assert config_export["lineNumber"] == 2

    check_port_export = next(
        (e for e in result["exports"] if e["name"] == "check_port"), None
    )
    assert check_port_export["lineNumber"] == 6


# ---- Call Graph ----


def test_extracts_simple_function_calls():
    root = _parse(
        """
fn validate(port: u16) -> bool {
    check_port(port)
}

fn main() {
    validate(8080);
}
"""
    )
    result = extractor.extract_call_graph(root)

    validate_calls = [e for e in result if e["caller"] == "validate"]
    assert any(e["callee"] == "check_port" for e in validate_calls)

    main_calls = [e for e in result if e["caller"] == "main"]
    assert any(e["callee"] == "validate" for e in main_calls)


def test_extracts_method_calls_field_expression():
    root = _parse(
        """
fn process(&self) {
    self.validate();
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "process"
    assert result[0]["callee"] == "self.validate"


def test_extracts_scoped_calls():
    root = _parse(
        """
fn create() {
    Vec::new();
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "create"
    assert result[0]["callee"] == "Vec::new"


def test_tracks_correct_caller_for_methods_in_impl_blocks():
    root = _parse(
        """
impl Config {
    fn validate(&self) -> bool {
        check_port(self.port)
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "validate"
    assert result[0]["callee"] == "check_port"


def test_reports_correct_line_numbers_for_calls():
    root = _parse(
        """
fn main() {
    foo();
    bar();
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 3
    assert result[1]["lineNumber"] == 4


def test_ignores_top_level_calls_no_caller():
    root = _parse(
        """
static X: i32 = compute();
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 0


# ---- Comprehensive ----


def test_handles_the_full_test_scenario_from_the_spec():
    root = _parse(
        """use std::collections::HashMap;
use std::io::{self, Read};

pub struct Config {
    name: String,
    port: u16,
}

impl Config {
    pub fn new(name: String, port: u16) -> Self {
        Config { name, port }
    }

    fn validate(&self) -> bool {
        check_port(self.port)
    }
}

pub fn check_port(port: u16) -> bool {
    port > 0
}

enum Status {
    Active,
    Inactive,
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 3
    fn_names = sorted(f["name"] for f in result["functions"])
    assert fn_names == ["check_port", "new", "validate"]

    new_fn = next((f for f in result["functions"] if f["name"] == "new"), None)
    assert new_fn["params"] == ["name", "port"]
    assert new_fn["returnType"] == "Self"

    validate_fn = next((f for f in result["functions"] if f["name"] == "validate"), None)
    assert validate_fn["params"] == []
    assert validate_fn["returnType"] == "bool"

    check_port_fn = next(
        (f for f in result["functions"] if f["name"] == "check_port"), None
    )
    assert check_port_fn["params"] == ["port"]
    assert check_port_fn["returnType"] == "bool"

    assert len(result["classes"]) == 2

    config_class = next((c for c in result["classes"] if c["name"] == "Config"), None)
    assert config_class is not None
    assert config_class["properties"] == ["name", "port"]
    assert "new" in config_class["methods"]
    assert "validate" in config_class["methods"]

    status_class = next((c for c in result["classes"] if c["name"] == "Status"), None)
    assert status_class is not None
    assert status_class["properties"] == ["Active", "Inactive"]
    assert status_class["methods"] == []

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "std::collections"
    assert result["imports"][0]["specifiers"] == ["HashMap"]
    assert result["imports"][1]["source"] == "std::io"
    assert result["imports"][1]["specifiers"] == ["self", "Read"]

    export_names = sorted(e["name"] for e in result["exports"])
    assert export_names == ["Config", "check_port", "new"]

    calls = extractor.extract_call_graph(root)
    validate_calls = [e for e in calls if e["caller"] == "validate"]
    assert len(validate_calls) == 1
    assert validate_calls[0]["callee"] == "check_port"


def test_handles_a_realistic_rust_module_with_traits_and_multiple_impls():
    root = _parse(
        """use std::fmt;
use std::io::{self, Write};

pub trait Displayable {
    fn display(&self) -> String;
}

pub struct Server {
    host: String,
    port: u16,
}

impl Server {
    pub fn new(host: String, port: u16) -> Self {
        Server { host, port }
    }

    pub fn start(&self) {
        listen(self.port);
    }
}

impl Displayable for Server {
    fn display(&self) -> String {
        format_server(self.host.clone(), self.port)
    }
}

fn listen(port: u16) {
    println!("Listening on port {}", port);
}

fn format_server(host: String, port: u16) -> String {
    format!("{}:{}", host, port)
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 5

    trait_ = next((c for c in result["classes"] if c["name"] == "Displayable"), None)
    assert trait_ is not None
    assert trait_["methods"] == ["display"]

    server = next((c for c in result["classes"] if c["name"] == "Server"), None)
    assert server is not None
    assert server["properties"] == ["host", "port"]
    assert "new" in server["methods"]
    assert "start" in server["methods"]
    assert "display" in server["methods"]

    export_names = sorted(e["name"] for e in result["exports"])
    assert "Displayable" in export_names
    assert "Server" in export_names
    assert "new" in export_names
    assert "start" in export_names
    assert "listen" not in export_names
    assert "format_server" not in export_names

    calls = extractor.extract_call_graph(root)
    start_calls = [e for e in calls if e["caller"] == "start"]
    assert any(e["callee"] == "listen" for e in start_calls)

    display_calls = [e for e in calls if e["caller"] == "display"]
    assert any(e["callee"] == "format_server" for e in display_calls)
