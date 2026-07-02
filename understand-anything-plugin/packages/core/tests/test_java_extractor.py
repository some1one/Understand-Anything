"""Tests for JavaExtractor. Port of java-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("java")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.java_extractor import JavaExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = JavaExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["java"]


# ---- Methods/Constructors (mapped to functions) ----


def test_extracts_methods_with_params_and_return_types():
    root = _parse(
        """public class Foo {
    public String getName(int id) {
        return "";
    }
    private void process(String data, int count) {
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "getName"
    assert result["functions"][0]["params"] == ["id"]
    assert result["functions"][0]["returnType"] == "String"

    assert result["functions"][1]["name"] == "process"
    assert result["functions"][1]["params"] == ["data", "count"]
    assert result["functions"][1]["returnType"] == "void"


def test_extracts_constructors():
    root = _parse(
        """public class Foo {
    public Foo(String name, int value) {
        this.name = name;
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "Foo"
    assert result["functions"][0]["params"] == ["name", "value"]
    assert result["functions"][0]["returnType"] is None


def test_extracts_methods_with_no_params():
    root = _parse(
        """public class Foo {
    public void run() {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "run"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] == "void"


def test_extracts_methods_with_generic_return_types():
    root = _parse(
        """public class Foo {
    public List<String> getItems() {
        return null;
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "getItems"
    assert result["functions"][0]["returnType"] == "List<String>"


def test_reports_correct_line_ranges_for_multi_line_methods():
    root = _parse(
        """public class Foo {
    public int calculate(
        int a,
        int b
    ) {
        int result = a + b;
        return result;
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 2
    assert result["functions"][0]["lineRange"][1] == 8


# ---- Classes ----


def test_extracts_class_with_methods_and_fields():
    root = _parse(
        """public class Server {
    private String host;
    private int port;
    public void start() {}
    public void stop() {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Server"
    assert result["classes"][0]["properties"] == ["host", "port"]
    assert result["classes"][0]["methods"] == ["start", "stop"]
    assert result["classes"][0]["lineRange"][0] == 1


def test_extracts_empty_class():
    root = _parse(
        """public class Empty {
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Empty"
    assert result["classes"][0]["properties"] == []
    assert result["classes"][0]["methods"] == []


def test_includes_constructors_in_methods_list():
    root = _parse(
        """public class Foo {
    public Foo() {}
    public void run() {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert result["classes"][0]["methods"] == ["Foo", "run"]


# ---- Interfaces ----


def test_extracts_interface_with_method_signatures():
    root = _parse(
        """interface Repository {
    List<User> findAll();
    User findById(int id);
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Repository"
    assert result["classes"][0]["methods"] == ["findAll", "findById"]
    assert result["classes"][0]["properties"] == []


def test_extracts_empty_interface():
    root = _parse(
        """interface Marker {
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Marker"
    assert result["classes"][0]["methods"] == []


# ---- Imports ----


def test_extracts_regular_imports():
    root = _parse(
        """import java.util.List;
import java.util.Map;
public class Foo {}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "java.util.List"
    assert result["imports"][0]["specifiers"] == ["List"]
    assert result["imports"][0]["lineNumber"] == 1
    assert result["imports"][1]["source"] == "java.util.Map"
    assert result["imports"][1]["specifiers"] == ["Map"]
    assert result["imports"][1]["lineNumber"] == 2


def test_extracts_wildcard_imports():
    root = _parse(
        """import java.util.*;
public class Foo {}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "java.util"
    assert result["imports"][0]["specifiers"] == ["*"]


def test_reports_correct_import_line_numbers():
    root = _parse(
        """import java.util.List;

import java.util.Map;
public class Foo {}
"""
    )
    result = extractor.extract_structure(root)

    assert result["imports"][0]["lineNumber"] == 1
    assert result["imports"][1]["lineNumber"] == 3


# ---- Exports ----


def test_exports_public_class_methods_and_constructor():
    root = _parse(
        """public class UserService {
    private String name;
    public UserService(String name) {
        this.name = name;
    }
    public void start() {}
    private void helper() {}
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "UserService" in export_names
    user_service_exports = [e for e in result["exports"] if e["name"] == "UserService"]
    assert len(user_service_exports) == 2  # class + constructor
    assert "start" in export_names
    assert "helper" not in export_names
    assert "name" not in export_names  # private field


def test_does_not_export_non_public_classes():
    root = _parse(
        """class Internal {
    void run() {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["exports"]) == 0


def test_exports_public_fields():
    root = _parse(
        """public class Config {
    public String apiKey;
    private int retries;
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Config" in export_names
    assert "apiKey" in export_names
    assert "retries" not in export_names


def test_exports_public_interface():
    root = _parse(
        """public interface Repository {
    void save();
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Repository" in export_names


# ---- Call Graph ----


def test_extracts_simple_method_calls():
    root = _parse(
        """public class Foo {
    public void process(int data) {
        transform(data);
        format(data);
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["caller"] == "process"
    assert result[0]["callee"] == "transform"
    assert result[1]["caller"] == "process"
    assert result[1]["callee"] == "format"


def test_extracts_qualified_method_calls():
    root = _parse(
        """public class Foo {
    private void log(String message) {
        System.out.println(message);
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "log"
    assert result[0]["callee"] == "System.out.println"


def test_extracts_object_creation_expressions():
    root = _parse(
        """public class Foo {
    public void create() {
        Bar b = new Bar();
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "create"
    assert result[0]["callee"] == "new Bar"


def test_tracks_correct_caller_for_constructors():
    root = _parse(
        """public class Foo {
    public Foo() {
        init();
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "Foo"
    assert result[0]["callee"] == "init"


def test_reports_correct_line_numbers_for_calls():
    root = _parse(
        """public class Foo {
    public void run() {
        foo();
        bar();
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 3
    assert result[1]["lineNumber"] == 4


def test_ignores_calls_outside_methods_no_caller():
    root = _parse(
        """public class Foo {
    private String value = String.valueOf(42);
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 0


# ---- Comprehensive ----


def test_handles_a_realistic_java_module():
    root = _parse(
        """import java.util.List;
import java.util.Map;

public class UserService {
    private String name;
    private int maxRetries;

    public UserService(String name) {
        this.name = name;
    }

    public List<User> getUsers(int limit) {
        return fetchFromDb(limit);
    }

    private void log(String message) {
        System.out.println(message);
    }
}

interface Repository {
    List<User> findAll();
    User findById(int id);
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 3
    assert sorted(f["name"] for f in result["functions"]) == sorted(
        ["UserService", "getUsers", "log"]
    )

    ctor = next((f for f in result["functions"] if f["name"] == "UserService"), None)
    assert ctor["params"] == ["name"]
    assert ctor["returnType"] is None

    get_users = next((f for f in result["functions"] if f["name"] == "getUsers"), None)
    assert get_users["params"] == ["limit"]
    assert get_users["returnType"] == "List<User>"

    log = next((f for f in result["functions"] if f["name"] == "log"), None)
    assert log["params"] == ["message"]
    assert log["returnType"] == "void"

    assert len(result["classes"]) == 2

    user_service = next(
        (c for c in result["classes"] if c["name"] == "UserService"), None
    )
    assert user_service is not None
    assert sorted(user_service["methods"]) == sorted(["UserService", "getUsers", "log"])
    assert sorted(user_service["properties"]) == sorted(["name", "maxRetries"])

    repository = next((c for c in result["classes"] if c["name"] == "Repository"), None)
    assert repository is not None
    assert repository["methods"] == ["findAll", "findById"]
    assert repository["properties"] == []

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "java.util.List"
    assert result["imports"][0]["specifiers"] == ["List"]
    assert result["imports"][1]["source"] == "java.util.Map"
    assert result["imports"][1]["specifiers"] == ["Map"]

    export_names = [e["name"] for e in result["exports"]]
    assert "UserService" in export_names
    assert "getUsers" in export_names
    assert "log" not in export_names
    assert "name" not in export_names
    assert "maxRetries" not in export_names

    calls = extractor.extract_call_graph(root)

    get_users_calls = [e for e in calls if e["caller"] == "getUsers"]
    assert any(e["callee"] == "fetchFromDb" for e in get_users_calls)

    log_calls = [e for e in calls if e["caller"] == "log"]
    assert any(e["callee"] == "System.out.println" for e in log_calls)
