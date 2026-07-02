"""Tests for CppExtractor (ported from cpp-extractor.test.ts)."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("cpp")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.cpp_extractor import CppExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = CppExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["cpp", "c"]


# ---- Functions ----


def test_extracts_top_level_functions_with_params_and_return_types():
    root = _parse(
        """
int add(int a, int b) {
    return a + b;
}

void greet(const char* name) {
    printf("Hello %s", name);
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "add"
    assert result["functions"][0]["params"] == ["a", "b"]
    assert result["functions"][0]["returnType"] == "int"

    assert result["functions"][1]["name"] == "greet"
    assert result["functions"][1]["params"] == ["name"]
    assert result["functions"][1]["returnType"] == "void"


def test_extracts_functions_with_no_params():
    root = _parse(
        """
int get_value() {
    return 42;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "get_value"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] == "int"


def test_reports_correct_line_ranges_for_multiline_functions():
    root = _parse(
        """
int multiline(
    int a,
    int b
) {
    int result = a + b;
    return result;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 2
    assert result["functions"][0]["lineRange"][1] == 8


def test_handles_pointer_and_reference_parameters():
    root = _parse(
        """
void process(int* ptr, const char& ref, int arr[]) {
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["params"] == ["ptr", "ref", "arr"]


# ---- Classes ----


def test_extracts_class_with_properties_and_method_declarations():
    root = _parse(
        """
class Server {
public:
    std::string host;
    int port;

    void start();
    int getPort() { return port; }
};
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Server"
    assert result["classes"][0]["properties"] == ["host", "port"]
    assert "start" in result["classes"][0]["methods"]
    assert "getPort" in result["classes"][0]["methods"]


def test_respects_access_specifiers_for_exports():
    root = _parse(
        """
class Foo {
private:
    int secret;
    void hidden();
public:
    int visible;
    void exposed();
};
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "exposed" in export_names
    assert "hidden" not in export_names
    assert "secret" not in export_names
    assert "Foo" in export_names


def test_defaults_class_members_to_private_access():
    root = _parse(
        """
class Priv {
    int x;
    void secret();
};
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Priv" in export_names
    assert "secret" not in export_names


def test_handles_inline_method_definitions():
    root = _parse(
        """
class Calculator {
public:
    int add(int a, int b) { return a + b; }
};
"""
    )
    result = extractor.extract_structure(root)

    assert "add" in result["classes"][0]["methods"]

    add_fn = next((f for f in result["functions"] if f["name"] == "add"), None)
    assert add_fn is not None
    assert add_fn["params"] == ["a", "b"]
    assert add_fn["returnType"] == "int"


# ---- Structs ----


def test_extracts_struct_with_fields():
    root = _parse(
        """
struct Point {
    int x;
    int y;
};
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Point"
    assert result["classes"][0]["properties"] == ["x", "y"]
    assert result["classes"][0]["methods"] == []


def test_defaults_struct_members_to_public_access_and_exports_them():
    root = _parse(
        """
struct Config {
    int port;
    void init();
};
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Config" in export_names
    assert "init" in export_names


# ---- Includes (imports) ----


def test_extracts_system_includes_angle_brackets():
    root = _parse(
        """
#include <iostream>
#include <vector>
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "iostream"
    assert result["imports"][0]["specifiers"] == ["iostream"]
    assert result["imports"][1]["source"] == "vector"


def test_extracts_local_includes_quoted():
    root = _parse(
        """
#include "config.h"
#include "utils/helper.h"
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "config.h"
    assert result["imports"][0]["specifiers"] == ["config.h"]
    assert result["imports"][1]["source"] == "utils/helper.h"


def test_reports_correct_import_line_numbers():
    root = _parse(
        """
#include <iostream>
#include "config.h"
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["lineNumber"] == 2
    assert result["imports"][1]["lineNumber"] == 3


# ---- Namespaces ----


def test_extracts_functions_inside_namespaces():
    root = _parse(
        """
namespace utils {
    int add(int a, int b) {
        return a + b;
    }

    void log(const char* msg) {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2
    names = [f["name"] for f in result["functions"]]
    assert "add" in names
    assert "log" in names


def test_extracts_classes_inside_namespaces():
    root = _parse(
        """
namespace models {
    class User {
    public:
        std::string name;
        int id;
    };
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "User"
    assert result["classes"][0]["properties"] == ["name", "id"]


# ---- Out-of-class method definitions ----


def test_associates_out_of_class_method_with_its_class():
    root = _parse(
        """
class Server {
public:
    void start();
};

void Server::start() {
    // implementation
}
"""
    )
    result = extractor.extract_structure(root)

    assert "start" in result["classes"][0]["methods"]

    start_fn = next((f for f in result["functions"] if f["name"] == "start"), None)
    assert start_fn is not None
    assert start_fn["returnType"] == "void"


# ---- Exports ----


def test_exports_non_static_functions_and_not_static_ones():
    root = _parse(
        """
int public_fn(int x) { return x; }

static void private_fn() {}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "public_fn" in export_names
    assert "private_fn" not in export_names


def test_reports_correct_export_line_numbers():
    root = _parse(
        """
struct Point {
    int x;
    int y;
};

int compute(int n) { return n * 2; }
"""
    )
    result = extractor.extract_structure(root)

    point_export = next((e for e in result["exports"] if e["name"] == "Point"), None)
    assert point_export is not None
    assert point_export["lineNumber"] == 2

    compute_export = next(
        (e for e in result["exports"] if e["name"] == "compute"), None
    )
    assert compute_export is not None
    assert compute_export["lineNumber"] == 7


# ---- Call Graph ----


def test_extracts_simple_function_calls():
    root = _parse(
        """
void helper(int x) {}

int main() {
    helper(42);
}
"""
    )
    result = extractor.extract_call_graph(root)

    main_calls = [e for e in result if e["caller"] == "main"]
    assert any(e["callee"] == "helper" for e in main_calls)


def test_extracts_multiple_calls_from_one_function():
    root = _parse(
        """
void foo() {}
void bar() {}

int main() {
    foo();
    bar();
}
"""
    )
    result = extractor.extract_call_graph(root)

    main_calls = [e for e in result if e["caller"] == "main"]
    assert len(main_calls) == 2
    assert any(e["callee"] == "foo" for e in main_calls)
    assert any(e["callee"] == "bar" for e in main_calls)


def test_extracts_calls_inside_namespace_functions():
    root = _parse(
        """
int baz(int x) { return x; }

namespace ns {
    void inner() {
        baz(42);
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert any(e["caller"] == "inner" and e["callee"] == "baz" for e in result)


def test_reports_correct_line_numbers_for_calls():
    root = _parse(
        """
int main() {
    foo();
    bar();
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 3
    assert result[1]["lineNumber"] == 4


def test_ignores_calls_outside_of_functions():
    root = _parse(
        """
int x = compute();
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 0


def test_tracks_member_function_calls_field_expression():
    root = _parse(
        """
void process() {
    obj.method();
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "process"
    assert result[0]["callee"] == "method"


# ---- Comprehensive C++ test ----


def test_handles_the_full_cpp_test_scenario_from_the_spec():
    root = _parse(
        """#include <iostream>
#include "config.h"

class Server {
public:
    std::string host;
    int port;

    void start();
    int getPort() { return port; }
};

void Server::start() {
    std::cout << "starting" << std::endl;
}

namespace utils {
    int add(int a, int b) {
        return a + b;
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "iostream"
    assert result["imports"][1]["source"] == "config.h"

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Server"
    assert result["classes"][0]["properties"] == ["host", "port"]
    assert "start" in result["classes"][0]["methods"]
    assert "getPort" in result["classes"][0]["methods"]

    assert len(result["functions"]) == 3
    fn_names = sorted(f["name"] for f in result["functions"])
    assert fn_names == ["add", "getPort", "start"]

    add_fn = next((f for f in result["functions"] if f["name"] == "add"), None)
    assert add_fn["params"] == ["a", "b"]
    assert add_fn["returnType"] == "int"

    get_port_fn = next(
        (f for f in result["functions"] if f["name"] == "getPort"), None
    )
    assert get_port_fn["params"] == []
    assert get_port_fn["returnType"] == "int"

    export_names = sorted(e["name"] for e in result["exports"])
    assert "Server" in export_names
    assert "start" in export_names
    assert "getPort" in export_names
    assert "add" in export_names


# ---- Comprehensive pure C test ----


def test_handles_pure_c_code_with_structs_and_functions():
    root = _parse(
        """#include <stdio.h>
#include "helper.h"

struct Point {
    int x;
    int y;
};

void print_point(struct Point* p) {
    printf("(%d, %d)", p->x, p->y);
}

int main() {
    struct Point p = {1, 2};
    print_point(&p);
    return 0;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "stdio.h"
    assert result["imports"][0]["specifiers"] == ["stdio.h"]
    assert result["imports"][1]["source"] == "helper.h"

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Point"
    assert result["classes"][0]["properties"] == ["x", "y"]
    assert result["classes"][0]["methods"] == []

    assert len(result["functions"]) == 2
    fn_names = sorted(f["name"] for f in result["functions"])
    assert fn_names == ["main", "print_point"]

    print_fn = next(
        (f for f in result["functions"] if f["name"] == "print_point"), None
    )
    assert print_fn["params"] == ["p"]
    assert print_fn["returnType"] == "void"

    main_fn = next((f for f in result["functions"] if f["name"] == "main"), None)
    assert main_fn["params"] == []
    assert main_fn["returnType"] == "int"

    export_names = [e["name"] for e in result["exports"]]
    assert "Point" in export_names
    assert "print_point" in export_names
    assert "main" in export_names

    calls = extractor.extract_call_graph(root)

    print_calls = [e for e in calls if e["caller"] == "print_point"]
    assert any(e["callee"] == "printf" for e in print_calls)

    main_calls = [e for e in calls if e["caller"] == "main"]
    assert any(e["callee"] == "print_point" for e in main_calls)


def test_handles_pure_c_code_without_any_classes_or_structs():
    root = _parse(
        """
#include <stdlib.h>

int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}

int main() {
    int result = factorial(5);
    return 0;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 0

    assert len(result["functions"]) == 2
    assert result["functions"][0]["name"] == "factorial"
    assert result["functions"][0]["params"] == ["n"]
    assert result["functions"][1]["name"] == "main"

    calls = extractor.extract_call_graph(root)
    assert any(
        e["caller"] == "factorial" and e["callee"] == "factorial" for e in calls
    )
    assert any(e["caller"] == "main" and e["callee"] == "factorial" for e in calls)
