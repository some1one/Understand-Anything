"""Tests for PythonExtractor, ported from python-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

from understand_core.plugins.extractors.python_extractor import PythonExtractor

pytest_lang = "python"
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


extractor = PythonExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["python"]


# ---- Functions ----


def test_extracts_simple_functions_with_type_annotations():
    root = parse(
        """
def hello(name: str) -> str:
    return f"Hello {name}"

def add(a: int, b: int) -> int:
    return a + b
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "hello"
    assert result["functions"][0]["params"] == ["name"]
    assert result["functions"][0]["returnType"] == "str"
    assert result["functions"][0]["lineRange"][0] > 0

    assert result["functions"][1]["name"] == "add"
    assert result["functions"][1]["params"] == ["a", "b"]
    assert result["functions"][1]["returnType"] == "int"


def test_extracts_functions_without_type_annotations():
    root = parse(
        """
def greet(name):
    print(name)

def noop():
    pass
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2
    assert result["functions"][0]["name"] == "greet"
    assert result["functions"][0]["params"] == ["name"]
    assert result["functions"][0]["returnType"] is None

    assert result["functions"][1]["name"] == "noop"
    assert result["functions"][1]["params"] == []


def test_extracts_functions_with_default_parameters():
    root = parse(
        """
def connect(host: str, port: int = 8080, timeout: float = 30.0):
    pass
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "connect"
    assert result["functions"][0]["params"] == ["host", "port", "timeout"]


def test_extracts_functions_with_args_and_kwargs():
    root = parse(
        """
def flexible(*args, **kwargs):
    pass
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["params"] == ["*args", "**kwargs"]


def test_extracts_decorated_functions():
    root = parse(
        """
@decorator
def decorated_func():
    pass

@app.route("/api")
def api_handler():
    pass
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2
    assert result["functions"][0]["name"] == "decorated_func"
    assert result["functions"][1]["name"] == "api_handler"


def test_reports_correct_line_ranges():
    root = parse(
        """
def multiline(
    a: int,
    b: int,
) -> int:
    result = a + b
    return result
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 2
    assert result["functions"][0]["lineRange"][1] == 7


# ---- Classes ----


def test_extracts_classes_with_methods_and_properties():
    root = parse(
        """
class DataProcessor:
    name: str

    def __init__(self, name: str):
        self.name = name

    def process(self, data: list) -> dict:
        return transform(data)
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "DataProcessor"
    assert "__init__" in result["classes"][0]["methods"]
    assert "process" in result["classes"][0]["methods"]
    assert "name" in result["classes"][0]["properties"]


def test_extracts_dataclass_style_annotated_properties():
    root = parse(
        """
class Config:
    name: str
    value: int
    debug: bool
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["properties"] == ["name", "value", "debug"]
    assert result["classes"][0]["methods"] == []


def test_extracts_decorated_classes():
    root = parse(
        """
@dataclass
class Config:
    name: str
    value: int = 0
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Config"
    assert "name" in result["classes"][0]["properties"]
    assert "value" in result["classes"][0]["properties"]


def test_extracts_decorated_methods_within_a_class():
    root = parse(
        """
class MyClass:
    @staticmethod
    def static_method():
        pass

    @classmethod
    def class_method(cls):
        pass

    @property
    def prop(self):
        return self._prop
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert "static_method" in result["classes"][0]["methods"]
    assert "class_method" in result["classes"][0]["methods"]
    assert "prop" in result["classes"][0]["methods"]


def test_filters_self_and_cls_from_method_params():
    root = parse(
        """
class Foo:
    def instance_method(self, x: int):
        pass

    @classmethod
    def class_method(cls, y: str):
        pass
"""
    )
    result = extractor.extract_structure(root)
    # Methods are on the class, but top-level functions should not include them
    assert len(result["functions"]) == 0
    assert result["classes"][0]["methods"] == ["instance_method", "class_method"]


def test_reports_correct_class_line_ranges():
    root = parse(
        """
class MyClass:
    def method_a(self):
        pass

    def method_b(self):
        pass
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["lineRange"][0] == 2
    assert result["classes"][0]["lineRange"][1] == 7


# ---- Imports ----


def test_extracts_simple_import_statements():
    root = parse(
        """
import os
import sys
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "os"
    assert result["imports"][0]["specifiers"] == ["os"]
    assert result["imports"][1]["source"] == "sys"
    assert result["imports"][1]["specifiers"] == ["sys"]


def test_extracts_from_import_statements():
    root = parse(
        """
from pathlib import Path
from typing import Optional, List
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "pathlib"
    assert result["imports"][0]["specifiers"] == ["Path"]
    assert result["imports"][1]["source"] == "typing"
    assert result["imports"][1]["specifiers"] == ["Optional", "List"]


def test_extracts_aliased_imports():
    root = parse(
        """
from foo import bar as baz
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "foo"
    assert result["imports"][0]["specifiers"] == ["baz"]


def test_extracts_dotted_module_imports():
    root = parse(
        """
import os.path
from os.path import join, exists
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "os.path"
    assert result["imports"][0]["specifiers"] == ["os.path"]
    assert result["imports"][1]["source"] == "os.path"
    assert result["imports"][1]["specifiers"] == ["join", "exists"]


def test_extracts_wildcard_imports():
    root = parse(
        """
from os.path import *
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "os.path"
    assert result["imports"][0]["specifiers"] == ["*"]


def test_handles_all_import_types_together():
    root = parse(
        """
import os
from pathlib import Path
from typing import Optional, List
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) >= 3


def test_reports_correct_import_line_numbers():
    root = parse(
        """
import os
from pathlib import Path
"""
    )
    result = extractor.extract_structure(root)

    assert result["imports"][0]["lineNumber"] == 2
    assert result["imports"][1]["lineNumber"] == 3


# ---- Exports ----


def test_treats_top_level_functions_as_exports():
    root = parse(
        """
def public_func():
    pass

def another_func(x: int) -> str:
    return str(x)
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "public_func" in export_names
    assert "another_func" in export_names
    assert len(result["exports"]) == 2


def test_treats_top_level_classes_as_exports():
    root = parse(
        """
class MyService:
    pass

class MyModel:
    pass
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "MyService" in export_names
    assert "MyModel" in export_names
    assert len(result["exports"]) == 2


def test_treats_decorated_top_level_definitions_as_exports():
    root = parse(
        """
@dataclass
class Config:
    name: str

@app.route("/")
def index():
    pass
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Config" in export_names
    assert "index" in export_names


def test_does_not_treat_imports_as_exports():
    root = parse(
        """
import os
from pathlib import Path

def my_func():
    pass
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["exports"]) == 1
    assert result["exports"][0]["name"] == "my_func"


# ---- Call Graph ----


def test_extracts_simple_function_calls():
    root = parse(
        """
def process(data):
    result = transform(data)
    return format_output(result)

def main():
    process([1, 2, 3])
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) >= 2

    process_callers = [e for e in result if e["caller"] == "process"]
    assert any(e["callee"] == "transform" for e in process_callers)
    assert any(e["callee"] == "format_output" for e in process_callers)

    main_callers = [e for e in result if e["caller"] == "main"]
    assert any(e["callee"] == "process" for e in main_callers)


def test_extracts_attribute_based_calls():
    root = parse(
        """
def process():
    self.method()
    os.path.join("a", "b")
    result.save()
"""
    )
    result = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in result]
    assert "self.method" in callees
    assert "os.path.join" in callees
    assert "result.save" in callees


def test_tracks_correct_caller_context_for_nested_calls():
    root = parse(
        """
def outer():
    helper()
    def inner():
        deep_call()
    another()
"""
    )
    result = extractor.extract_call_graph(root)

    outer_calls = [e for e in result if e["caller"] == "outer"]
    assert any(e["callee"] == "helper" for e in outer_calls)
    assert any(e["callee"] == "another" for e in outer_calls)

    inner_calls = [e for e in result if e["caller"] == "inner"]
    assert any(e["callee"] == "deep_call" for e in inner_calls)


def test_reports_correct_line_numbers_for_calls():
    root = parse(
        """
def main():
    foo()
    bar()
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 3
    assert result[1]["lineNumber"] == 4


def test_ignores_top_level_calls():
    root = parse(
        """
print("hello")
main()
"""
    )
    result = extractor.extract_call_graph(root)

    # Top-level calls have no enclosing function, so they are skipped
    assert len(result) == 0


def test_handles_calls_inside_class_methods():
    root = parse(
        """
class Service:
    def start(self):
        self.setup()
        run_server()
"""
    )
    result = extractor.extract_call_graph(root)

    start_calls = [e for e in result if e["caller"] == "start"]
    assert any(e["callee"] == "self.setup" for e in start_calls)
    assert any(e["callee"] == "run_server" for e in start_calls)


# ---- Comprehensive ----


def test_handles_a_realistic_python_module():
    root = parse(
        """
import os
from pathlib import Path
from typing import Optional, List

class FileProcessor:
    name: str
    verbose: bool

    def __init__(self, name: str, verbose: bool = False):
        self.name = name
        self.verbose = verbose

    def process(self, paths: List[str]) -> dict:
        results = {}
        for p in paths:
            results[p] = self._read_file(p)
        return results

    def _read_file(self, path: str) -> Optional[str]:
        full = Path(path)
        if full.exists():
            return full.read_text()
        return None

def create_processor(name: str) -> FileProcessor:
    return FileProcessor(name)

@staticmethod
def utility_func(*args, **kwargs) -> None:
    print(args, kwargs)
"""
    )
    result = extractor.extract_structure(root)

    # Imports
    assert len(result["imports"]) >= 3

    # Class
    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "FileProcessor"
    assert "__init__" in result["classes"][0]["methods"]
    assert "process" in result["classes"][0]["methods"]
    assert "_read_file" in result["classes"][0]["methods"]
    assert "name" in result["classes"][0]["properties"]
    assert "verbose" in result["classes"][0]["properties"]

    # Top-level functions
    assert any(f["name"] == "create_processor" for f in result["functions"])
    assert any(f["name"] == "utility_func" for f in result["functions"])

    # Exports (top-level defs)
    export_names = [e["name"] for e in result["exports"]]
    assert "FileProcessor" in export_names
    assert "create_processor" in export_names
    assert "utility_func" in export_names

    # Call graph
    calls = extractor.extract_call_graph(root)
    assert len(calls) > 0
