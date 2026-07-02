"""Tests for RubyExtractor. Port of ruby-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("ruby")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.ruby_extractor import RubyExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = RubyExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["ruby"]


# ---- functions / methods ----


def test_extracts_simple_methods():
    root = _parse(
        """
def hello(name)
  puts name
end

def add(a, b)
  a + b
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "hello"
    assert result["functions"][0]["params"] == ["name"]
    assert result["functions"][0]["lineRange"][0] > 0

    assert result["functions"][1]["name"] == "add"
    assert result["functions"][1]["params"] == ["a", "b"]


def test_extracts_methods_with_optional_parameters():
    root = _parse(
        """
def connect(host, port = 8080, timeout = 30.0)
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "connect"
    assert result["functions"][0]["params"] == ["host", "port", "timeout"]


def test_extracts_methods_with_splat_hash_splat_and_block_parameters():
    root = _parse(
        """
def flexible(*args, **kwargs, &block)
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["params"] == ["*args", "**kwargs", "&block"]


def test_extracts_methods_with_no_parameters():
    root = _parse(
        """
def noop
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "noop"
    assert result["functions"][0]["params"] == []


def test_does_not_assign_return_types():
    root = _parse(
        """
def compute(x)
  x * 2
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["returnType"] is None


def test_reports_correct_line_ranges():
    root = _parse(
        """
def multiline(
    a,
    b
)
  result = a + b
  result
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 2
    assert result["functions"][0]["lineRange"][1] == 8


# ---- classes ----


def test_extracts_classes_with_methods():
    root = _parse(
        """
class UserService
  def initialize(name)
    @name = name
  end

  def find_user(id)
    db_query(id)
  end
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "UserService"
    assert "initialize" in result["classes"][0]["methods"]
    assert "find_user" in result["classes"][0]["methods"]


def test_extracts_attr_accessor_reader_writer_as_properties():
    root = _parse(
        """
class Model
  attr_accessor :name, :email
  attr_reader :id
  attr_writer :status
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["properties"] == ["name", "email", "id", "status"]
    assert result["classes"][0]["methods"] == []


def test_extracts_singleton_methods_within_classes():
    root = _parse(
        """
class Factory
  def self.create(attrs)
    new(attrs)
  end

  def instance_method
  end
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert "self.create" in result["classes"][0]["methods"]
    assert "instance_method" in result["classes"][0]["methods"]


def test_also_adds_class_methods_to_the_functions_array():
    root = _parse(
        """
class Svc
  def run(x)
    x
  end
end
"""
    )
    result = extractor.extract_structure(root)

    assert any(f["name"] == "run" for f in result["functions"])


def test_extracts_namespaced_class_names():
    root = _parse(
        """
class Foo::Bar
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Foo::Bar"


def test_reports_correct_class_line_ranges():
    root = _parse(
        """
class MyClass
  def method_a
  end

  def method_b
  end
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["lineRange"][0] == 2
    assert result["classes"][0]["lineRange"][1] == 8


# ---- modules ----


def test_treats_modules_as_classes():
    root = _parse(
        """
module Helpers
  def format_date(date)
    date.strftime("%Y-%m-%d")
  end
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Helpers"
    assert "format_date" in result["classes"][0]["methods"]


def test_extracts_module_properties_from_attr_calls():
    root = _parse(
        """
module Config
  attr_accessor :debug
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert "debug" in result["classes"][0]["properties"]


# ---- imports ----


def test_extracts_require_statements():
    root = _parse(
        """
require "json"
require "net/http"
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "json"
    assert result["imports"][0]["specifiers"] == ["json"]
    assert result["imports"][1]["source"] == "net/http"
    assert result["imports"][1]["specifiers"] == ["net/http"]


def test_extracts_require_relative_statements():
    root = _parse(
        """
require_relative "./helper"
require_relative "../lib/utils"
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "./helper"
    assert result["imports"][1]["source"] == "../lib/utils"


def test_reports_correct_import_line_numbers():
    root = _parse(
        """
require "json"
require_relative "./helper"
"""
    )
    result = extractor.extract_structure(root)

    assert result["imports"][0]["lineNumber"] == 2
    assert result["imports"][1]["lineNumber"] == 3


def test_handles_mixed_require_and_require_relative():
    root = _parse(
        """
require "json"
require_relative "./helper"
require "yaml"
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 3
    assert result["imports"][0]["source"] == "json"
    assert result["imports"][1]["source"] == "./helper"
    assert result["imports"][2]["source"] == "yaml"


# ---- exports ----


def test_treats_top_level_methods_as_exports():
    root = _parse(
        """
def public_func
end

def another_func(x)
end
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "public_func" in export_names
    assert "another_func" in export_names
    assert len(result["exports"]) == 2


def test_treats_top_level_classes_as_exports():
    root = _parse(
        """
class MyService
end

class MyModel
end
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "MyService" in export_names
    assert "MyModel" in export_names
    assert len(result["exports"]) == 2


def test_treats_top_level_modules_as_exports():
    root = _parse(
        """
module Helpers
end
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Helpers" in export_names


def test_does_not_treat_imports_as_exports():
    root = _parse(
        """
require "json"
require_relative "./helper"

def my_func
end
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["exports"]) == 1
    assert result["exports"][0]["name"] == "my_func"


# ---- Call Graph ----


def test_extracts_simple_method_calls():
    root = _parse(
        """
def process(data)
  result = transform(data)
  format_output(result)
end

def main
  process([1, 2, 3])
end
"""
    )
    result = extractor.extract_call_graph(root)

    process_callers = [e for e in result if e["caller"] == "process"]
    assert any(e["callee"] == "transform" for e in process_callers)
    assert any(e["callee"] == "format_output" for e in process_callers)

    main_callers = [e for e in result if e["caller"] == "main"]
    assert any(e["callee"] == "process" for e in main_callers)


def test_extracts_receiver_based_calls():
    root = _parse(
        """
def process
  result.save
  date.strftime("%Y-%m-%d")
end
"""
    )
    result = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in result]
    assert "result.save" in callees
    assert "date.strftime" in callees


def test_tracks_correct_caller_context_for_calls_inside_class_methods():
    root = _parse(
        """
class Service
  def start
    setup
    run_server
  end
end
"""
    )
    result = extractor.extract_call_graph(root)

    start_calls = [e for e in result if e["caller"] == "start"]
    assert any(e["callee"] == "setup" for e in start_calls)
    assert any(e["callee"] == "run_server" for e in start_calls)


def test_does_not_include_require_in_call_graph():
    root = _parse(
        """
def setup
  require "json"
  do_work
end
"""
    )
    result = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in result]
    assert "require" not in callees
    assert "do_work" in callees


def test_does_not_include_attr_macros_in_call_graph():
    root = _parse(
        """
class Foo
  attr_accessor :bar

  def init
    setup
  end
end
"""
    )
    result = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in result]
    assert "attr_accessor" not in callees
    assert "setup" in callees


def test_reports_correct_line_numbers_for_calls():
    root = _parse(
        """
def main
  foo
  bar
end
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 3
    assert result[1]["lineNumber"] == 4


def test_ignores_top_level_calls():
    root = _parse(
        """
puts "hello"
main
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 0


def test_tracks_singleton_method_callers_with_self_prefix():
    root = _parse(
        """
class Foo
  def self.create(attrs)
    new(attrs)
  end
end
"""
    )
    result = extractor.extract_call_graph(root)

    create_calls = [e for e in result if e["caller"] == "self.create"]
    assert any(e["callee"] == "new" for e in create_calls)


# ---- comprehensive ----


def test_handles_the_full_test_fixture():
    root = _parse(
        """
require "json"
require_relative "./helper"

class UserService
  attr_accessor :name, :email
  attr_reader :id

  def initialize(name, email)
    @name = name
    @email = email
  end

  def find_user(id)
    result = db_query(id)
    format_user(result)
  end

  def self.create(attrs)
    new(attrs[:name], attrs[:email])
  end
end

module Helpers
  def format_date(date)
    date.strftime("%Y-%m-%d")
  end
end

def standalone_helper(x)
  puts x.to_s
end
"""
    )
    result = extractor.extract_structure(root)

    func_names = [f["name"] for f in result["functions"]]
    assert "initialize" in func_names
    assert "find_user" in func_names
    assert "self.create" in func_names
    assert "format_date" in func_names
    assert "standalone_helper" in func_names
    assert len(result["functions"]) == 5

    assert len(result["classes"]) == 2

    user_service = next((c for c in result["classes"] if c["name"] == "UserService"), None)
    assert user_service is not None
    assert "initialize" in user_service["methods"]
    assert "find_user" in user_service["methods"]
    assert "self.create" in user_service["methods"]
    for prop in ["name", "email", "id"]:
        assert prop in user_service["properties"]

    helpers = next((c for c in result["classes"] if c["name"] == "Helpers"), None)
    assert helpers is not None
    assert "format_date" in helpers["methods"]

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "json"
    assert result["imports"][1]["source"] == "./helper"

    export_names = [e["name"] for e in result["exports"]]
    assert "UserService" in export_names
    assert "Helpers" in export_names
    assert "standalone_helper" in export_names

    calls = extractor.extract_call_graph(root)

    find_user_calls = [e for e in calls if e["caller"] == "find_user"]
    assert any(e["callee"] == "db_query" for e in find_user_calls)
    assert any(e["callee"] == "format_user" for e in find_user_calls)

    standalone_helper_calls = [e for e in calls if e["caller"] == "standalone_helper"]
    assert any(e["callee"] == "puts" for e in standalone_helper_calls)

    all_callees = [e["callee"] for e in calls]
    assert "require" not in all_callees
    assert "require_relative" not in all_callees
