"""Tests for PhpExtractor. Port of php-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("php")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.php_extractor import PhpExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = PhpExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["php"]


# ---- functions ----


def test_extracts_top_level_functions_with_params_and_return_types():
    root = _parse(
        """<?php
function helper(string $x): string {
    return strtoupper($x);
}

function greet(string $name, int $times): void {
    echo $name;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "helper"
    assert result["functions"][0]["params"] == ["$x"]
    assert result["functions"][0]["returnType"] == "string"

    assert result["functions"][1]["name"] == "greet"
    assert result["functions"][1]["params"] == ["$name", "$times"]
    assert result["functions"][1]["returnType"] == "void"


def test_extracts_functions_without_return_type():
    root = _parse(
        """<?php
function noReturn($x) {
    echo $x;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "noReturn"
    assert result["functions"][0]["returnType"] is None


def test_extracts_functions_with_no_parameters():
    root = _parse(
        """<?php
function noop(): void {
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "noop"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] == "void"


def test_reports_correct_line_ranges():
    root = _parse(
        """<?php
function multiline(
    string $a,
    string $b
): string {
    $result = $a . $b;
    return $result;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 2
    assert result["functions"][0]["lineRange"][1] == 8


# ---- classes ----


def test_extracts_classes_with_methods_and_properties():
    root = _parse(
        """<?php
class UserService {
    private string $name;
    protected int $maxRetries;

    public function __construct(string $name) {
        $this->name = $name;
    }

    public function getUser(int $id): User {
        return $this->fetchFromDb($id);
    }

    private function log(string $message): void {
        error_log($message);
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "UserService"
    assert "__construct" in result["classes"][0]["methods"]
    assert "getUser" in result["classes"][0]["methods"]
    assert "log" in result["classes"][0]["methods"]
    assert len(result["classes"][0]["methods"]) == 3
    assert "name" in result["classes"][0]["properties"]
    assert "maxRetries" in result["classes"][0]["properties"]
    assert len(result["classes"][0]["properties"]) == 2


def test_also_adds_class_methods_to_the_functions_array():
    root = _parse(
        """<?php
class Svc {
    public function run(string $x): string {
        return $x;
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert any(f["name"] == "run" for f in result["functions"])
    assert result["functions"][0]["params"] == ["$x"]
    assert result["functions"][0]["returnType"] == "string"


def test_extracts_classes_with_static_methods():
    root = _parse(
        """<?php
class Factory {
    public static function create(): self {
        return new self();
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert "create" in result["classes"][0]["methods"]


def test_extracts_nullable_and_optional_type_properties():
    root = _parse(
        """<?php
class Config {
    public ?string $nullable;
    public static int $counter = 0;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert "nullable" in result["classes"][0]["properties"]
    assert "counter" in result["classes"][0]["properties"]


def test_reports_correct_class_line_ranges():
    root = _parse(
        """<?php
class MyClass {
    public function a(): void {}
    public function b(): void {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["lineRange"][0] == 2
    assert result["classes"][0]["lineRange"][1] == 5


# ---- interfaces ----


def test_extracts_interfaces_with_method_signatures():
    root = _parse(
        """<?php
interface Loggable {
    public function log(string $msg): void;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Loggable"
    assert "log" in result["classes"][0]["methods"]
    assert result["classes"][0]["properties"] == []


def test_treats_interfaces_as_exports():
    root = _parse(
        """<?php
interface Repository {
    public function find(int $id): mixed;
    public function save(object $entity): void;
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Repository" in export_names


# ---- imports (use statements) ----


def test_extracts_simple_use_statements():
    root = _parse(
        """<?php
use App\\Models\\User;
use App\\Contracts\\Repository;
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "App\\Models\\User"
    assert result["imports"][0]["specifiers"] == ["User"]
    assert result["imports"][1]["source"] == "App\\Contracts\\Repository"
    assert result["imports"][1]["specifiers"] == ["Repository"]


def test_extracts_grouped_use_statements():
    root = _parse(
        """<?php
use App\\Models\\{User, Post};
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["specifiers"] == ["User", "Post"]


def test_extracts_aliased_use_statements():
    root = _parse(
        """<?php
use App\\Contracts\\Repository as Repo;
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "App\\Contracts\\Repository"
    assert result["imports"][0]["specifiers"] == ["Repository"]


def test_reports_correct_import_line_numbers():
    root = _parse(
        """<?php
use App\\Models\\User;
use App\\Models\\Post;
"""
    )
    result = extractor.extract_structure(root)

    assert result["imports"][0]["lineNumber"] == 2
    assert result["imports"][1]["lineNumber"] == 3


# ---- exports ----


def test_treats_top_level_functions_as_exports():
    root = _parse(
        """<?php
function publicFunc(): void {}
function anotherFunc(string $x): string { return $x; }
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "publicFunc" in export_names
    assert "anotherFunc" in export_names
    assert len(result["exports"]) == 2


def test_treats_classes_as_exports():
    root = _parse(
        """<?php
class MyService {}
class MyModel {}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "MyService" in export_names
    assert "MyModel" in export_names
    assert len(result["exports"]) == 2


def test_does_not_treat_use_statements_as_exports():
    root = _parse(
        """<?php
use App\\Models\\User;

function myFunc(): void {}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["exports"]) == 1
    assert result["exports"][0]["name"] == "myFunc"


# ---- Call Graph ----


def test_extracts_standalone_function_calls():
    root = _parse(
        """<?php
function process(string $data): string {
    $result = transform($data);
    return format_output($result);
}
"""
    )
    result = extractor.extract_call_graph(root)

    callees = [e["callee"] for e in result]
    assert all(e["caller"] == "process" for e in result)
    assert "transform" in callees
    assert "format_output" in callees


def test_extracts_instance_method_calls():
    root = _parse(
        """<?php
class Svc {
    public function getUser(int $id): User {
        return $this->fetchFromDb($id);
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert any(
        e["caller"] == "getUser" and e["callee"] == "$this->fetchFromDb" for e in result
    )


def test_extracts_static_method_calls():
    root = _parse(
        """<?php
class Foo {
    public function doWork(): void {
        $result = Bar::staticMethod();
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert any(
        e["caller"] == "doWork" and e["callee"] == "Bar::staticMethod" for e in result
    )


def test_tracks_correct_caller_context_across_nested_calls():
    root = _parse(
        """<?php
class Service {
    public function start(): void {
        $this->setup();
        run_server();
    }

    private function setup(): void {
        init_config();
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    start_calls = [e for e in result if e["caller"] == "start"]
    assert any(e["callee"] == "$this->setup" for e in start_calls)
    assert any(e["callee"] == "run_server" for e in start_calls)

    setup_calls = [e for e in result if e["caller"] == "setup"]
    assert any(e["callee"] == "init_config" for e in setup_calls)


def test_ignores_top_level_calls():
    root = _parse(
        """<?php
echo "hello";
main();
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 0


def test_reports_correct_line_numbers_for_calls():
    root = _parse(
        """<?php
function main(): void {
    foo();
    bar();
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 3
    assert result[1]["lineNumber"] == 4


# ---- comprehensive ----


def test_handles_the_full_test_fixture():
    root = _parse(
        """<?php
namespace App\\Services;

use App\\Models\\User;
use App\\Contracts\\Repository;

class UserService {
    private string $name;
    protected int $maxRetries;

    public function __construct(string $name) {
        $this->name = $name;
    }

    public function getUser(int $id): User {
        return $this->fetchFromDb($id);
    }

    private function log(string $message): void {
        error_log($message);
    }
}

function helper(string $x): string {
    return strtoupper($x);
}
"""
    )
    result = extractor.extract_structure(root)

    func_names = [f["name"] for f in result["functions"]]
    assert "__construct" in func_names
    assert "getUser" in func_names
    assert "log" in func_names
    assert "helper" in func_names
    assert len(result["functions"]) == 4

    assert len(result["classes"]) == 1
    user_service = result["classes"][0]
    assert user_service["name"] == "UserService"
    assert "__construct" in user_service["methods"]
    assert "getUser" in user_service["methods"]
    assert "log" in user_service["methods"]
    assert "name" in user_service["properties"]
    assert "maxRetries" in user_service["properties"]

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "App\\Models\\User"
    assert result["imports"][0]["specifiers"] == ["User"]
    assert result["imports"][1]["source"] == "App\\Contracts\\Repository"
    assert result["imports"][1]["specifiers"] == ["Repository"]

    export_names = [e["name"] for e in result["exports"]]
    assert "UserService" in export_names
    assert "helper" in export_names
    assert len(result["exports"]) == 2

    get_user = next((f for f in result["functions"] if f["name"] == "getUser"), None)
    assert get_user is not None
    assert get_user["returnType"] == "User"

    log = next((f for f in result["functions"] if f["name"] == "log"), None)
    assert log is not None
    assert log["returnType"] == "void"

    helper = next((f for f in result["functions"] if f["name"] == "helper"), None)
    assert helper is not None
    assert helper["returnType"] == "string"

    calls = extractor.extract_call_graph(root)

    get_user_calls = [e for e in calls if e["caller"] == "getUser"]
    assert any(e["callee"] == "$this->fetchFromDb" for e in get_user_calls)

    log_calls = [e for e in calls if e["caller"] == "log"]
    assert any(e["callee"] == "error_log" for e in log_calls)

    helper_calls = [e for e in calls if e["caller"] == "helper"]
    assert any(e["callee"] == "strtoupper" for e in helper_calls)


# ---- block-scoped namespaces ----


def test_extracts_classes_and_functions_inside_block_scoped_namespaces():
    root = _parse(
        """<?php
namespace App\\Controllers {
    class UserController {
        public function index(): void {}
    }

    function helperInNs(): string {
        return "ok";
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "UserController"
    assert "index" in result["classes"][0]["methods"]

    assert any(f["name"] == "helperInNs" for f in result["functions"])
    assert any(f["name"] == "index" for f in result["functions"])

    export_names = [e["name"] for e in result["exports"]]
    assert "UserController" in export_names
    assert "helperInNs" in export_names


def test_extracts_interfaces_inside_block_scoped_namespaces():
    root = _parse(
        """<?php
namespace App\\Contracts {
    interface Repository {
        public function find(int $id): mixed;
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Repository"
    assert "find" in result["classes"][0]["methods"]


def test_extracts_use_statements_inside_block_scoped_namespaces():
    root = _parse(
        """<?php
namespace App\\Services {
    use App\\Models\\User;

    class UserService {
        public function get(): void {}
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "App\\Models\\User"
    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "UserService"


# ---- nullable return types ----


def test_extracts_nullable_return_type():
    root = _parse(
        """<?php
function findUser(int $id): ?User {
    return null;
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["returnType"] == "?User"
