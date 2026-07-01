"""Tests for GoExtractor, ported from go-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

from understand_core.plugins.extractors.go_extractor import GoExtractor

pytest_lang = "go"
try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser(pytest_lang)
except Exception:  # pragma: no cover
    _parser = None

pytestmark = pytest.mark.skipif(
    _parser is None, reason="tree-sitter grammar unavailable"
)


def parse(code: str):
    return parse_source(_parser, code)


extractor = GoExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["go"]


# ---- Functions ----


def test_extracts_functions_with_params_and_return_types():
    root = parse(
        """package main

func NewServer(host string, port int) *Server {
    return nil
}

func helper(x int) string {
    return ""
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "NewServer"
    assert result["functions"][0]["params"] == ["host", "port"]
    assert result["functions"][0]["returnType"] == "*Server"
    assert result["functions"][0]["lineRange"][0] == 3

    assert result["functions"][1]["name"] == "helper"
    assert result["functions"][1]["params"] == ["x"]
    assert result["functions"][1]["returnType"] == "string"


def test_extracts_functions_with_no_params_and_no_return_type():
    root = parse(
        """package main

func noop() {
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "noop"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] is None


def test_extracts_functions_with_multiple_return_types():
    root = parse(
        """package main

func divide(a, b float64) (float64, error) {
    return 0, nil
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "divide"
    assert result["functions"][0]["params"] == ["a", "b"]
    assert result["functions"][0]["returnType"] == "(float64, error)"


def test_reports_correct_line_ranges_for_multi_line_functions():
    root = parse(
        """package main

func multiline(
    a int,
    b int,
) int {
    result := a + b
    return result
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 3
    assert result["functions"][0]["lineRange"][1] == 9


# ---- Methods ----


def test_extracts_methods_with_receivers():
    root = parse(
        """package main

type Server struct {
    Host string
}

func (s *Server) Start() error {
    return nil
}

func (s Server) Name() string {
    return s.Host
}
"""
    )
    result = extractor.extract_structure(root)

    method_names = [f["name"] for f in result["functions"]]
    assert "Start" in method_names
    assert "Name" in method_names

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Server"
    assert "Start" in result["classes"][0]["methods"]
    assert "Name" in result["classes"][0]["methods"]

    start_fn = next((f for f in result["functions"] if f["name"] == "Start"), None)
    assert start_fn is not None
    assert start_fn["returnType"] == "error"
    assert start_fn["params"] == []


# ---- Structs ----


def test_extracts_struct_with_fields():
    root = parse(
        """package main

type Server struct {
    Host string
    Port int
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Server"
    assert result["classes"][0]["properties"] == ["Host", "Port"]
    assert result["classes"][0]["methods"] == []
    assert result["classes"][0]["lineRange"][0] == 3


def test_extracts_empty_struct():
    root = parse(
        """package main

type Empty struct{}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Empty"
    assert result["classes"][0]["properties"] == []
    assert result["classes"][0]["methods"] == []


def test_extracts_struct_with_multiple_name_fields_sharing_a_type():
    root = parse(
        """package main

type Point struct {
    X, Y int
    Z    float64
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert "X" in result["classes"][0]["properties"]
    assert "Y" in result["classes"][0]["properties"]
    assert "Z" in result["classes"][0]["properties"]


# ---- Interfaces ----


def test_extracts_interface_with_method_signatures():
    root = parse(
        """package main

type Reader interface {
    Read(buf []byte) (int, error)
    Close() error
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Reader"
    assert result["classes"][0]["methods"] == ["Read", "Close"]
    assert result["classes"][0]["properties"] == []


def test_extracts_empty_interface():
    root = parse(
        """package main

type Any interface{}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Any"
    assert result["classes"][0]["methods"] == []


# ---- Imports ----


def test_extracts_grouped_imports():
    root = parse(
        """package main

import (
    "fmt"
    "os"
)
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "fmt"
    assert result["imports"][0]["specifiers"] == ["fmt"]
    assert result["imports"][1]["source"] == "os"
    assert result["imports"][1]["specifiers"] == ["os"]


def test_extracts_single_import():
    root = parse(
        """package main

import "fmt"
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "fmt"
    assert result["imports"][0]["specifiers"] == ["fmt"]


def test_extracts_imports_with_path_components():
    root = parse(
        """package main

import "net/http"
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "net/http"
    assert result["imports"][0]["specifiers"] == ["http"]


def test_extracts_aliased_imports():
    root = parse(
        """package main

import (
    f "fmt"
    myhttp "net/http"
)
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "fmt"
    assert result["imports"][0]["specifiers"] == ["f"]
    assert result["imports"][1]["source"] == "net/http"
    assert result["imports"][1]["specifiers"] == ["myhttp"]


def test_reports_correct_import_line_numbers():
    root = parse(
        """package main

import (
    "fmt"
    "os"
)
"""
    )
    result = extractor.extract_structure(root)

    assert result["imports"][0]["lineNumber"] == 4
    assert result["imports"][1]["lineNumber"] == 5


# ---- Exports ----


def test_exports_uppercase_function_and_type_names():
    root = parse(
        """package main

type Server struct {
    Host string
    Port int
}

func (s *Server) Start() error {
    return nil
}

func NewServer(host string, port int) *Server {
    return nil
}

func helper(x int) string {
    return ""
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Server" in export_names
    assert "Start" in export_names
    assert "NewServer" in export_names
    assert "helper" not in export_names
    assert len(result["exports"]) == 3


def test_does_not_export_lowercase_names():
    root = parse(
        """package main

type internal struct {
    value int
}

func private() {}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["exports"]) == 0


def test_exports_uppercase_interface_names():
    root = parse(
        """package main

type Writer interface {
    Write(data []byte) error
}

type reader interface {
    read() error
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Writer" in export_names
    assert "reader" not in export_names


# ---- Call Graph ----


def test_extracts_simple_function_calls():
    root = parse(
        """package main

func process(data int) {
    transform(data)
    formatOutput(data)
}

func main() {
    process(42)
}
"""
    )
    result = extractor.extract_call_graph(root)

    process_calls = [e for e in result if e["caller"] == "process"]
    assert any(e["callee"] == "transform" for e in process_calls)
    assert any(e["callee"] == "formatOutput" for e in process_calls)

    main_calls = [e for e in result if e["caller"] == "main"]
    assert any(e["callee"] == "process" for e in main_calls)


def test_extracts_selector_expression_calls():
    root = parse(
        """package main

import "fmt"

func Start() {
    fmt.Println("starting")
}

func helper(x int) string {
    return fmt.Sprintf("%d", x)
}
"""
    )
    result = extractor.extract_call_graph(root)

    start_calls = [e for e in result if e["caller"] == "Start"]
    assert any(e["callee"] == "fmt.Println" for e in start_calls)

    helper_calls = [e for e in result if e["caller"] == "helper"]
    assert any(e["callee"] == "fmt.Sprintf" for e in helper_calls)


def test_tracks_correct_caller_for_methods():
    root = parse(
        """package main

import "fmt"

func (s *Server) Start() error {
    fmt.Println("starting")
    return nil
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "Start"
    assert result[0]["callee"] == "fmt.Println"


def test_reports_correct_line_numbers_for_calls():
    root = parse(
        """package main

func main() {
    foo()
    bar()
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 4
    assert result[1]["lineNumber"] == 5


def test_ignores_top_level_calls():
    root = parse(
        """package main

var _ = fmt.Println("hello")
"""
    )
    result = extractor.extract_call_graph(root)

    # Top-level calls have no enclosing function, so they are skipped
    assert len(result) == 0


# ---- Comprehensive ----


def test_handles_a_realistic_go_module():
    root = parse(
        """package main

import (
    "fmt"
    "os"
)

type Server struct {
    Host string
    Port int
}

func (s *Server) Start() error {
    fmt.Println("starting")
    return nil
}

func NewServer(host string, port int) *Server {
    return &Server{Host: host, Port: port}
}

func helper(x int) string {
    return fmt.Sprintf("%d", x)
}
"""
    )
    result = extractor.extract_structure(root)

    # Functions: Start, NewServer, helper
    assert len(result["functions"]) == 3
    assert sorted(f["name"] for f in result["functions"]) == sorted(
        ["Start", "NewServer", "helper"]
    )

    # Struct: Server with properties Host, Port and method Start
    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Server"
    assert result["classes"][0]["properties"] == ["Host", "Port"]
    assert "Start" in result["classes"][0]["methods"]

    # Imports: fmt, os
    assert len(result["imports"]) == 2
    assert sorted(i["source"] for i in result["imports"]) == ["fmt", "os"]

    # Exports: Server, Start, NewServer (all uppercase)
    export_names = sorted(e["name"] for e in result["exports"])
    assert export_names == ["NewServer", "Server", "Start"]

    # Call graph
    calls = extractor.extract_call_graph(root)
    start_calls = [e for e in calls if e["caller"] == "Start"]
    assert any(e["callee"] == "fmt.Println" for e in start_calls)

    helper_calls = [e for e in calls if e["caller"] == "helper"]
    assert any(e["callee"] == "fmt.Sprintf" for e in helper_calls)
