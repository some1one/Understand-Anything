"""Tests for CSharpExtractor. Port of csharp-extractor.test.ts."""

from __future__ import annotations

from tests._ts_helper import parse_source

import pytest

try:
    from tree_sitter_language_pack import get_parser

    _parser = get_parser("c_sharp")
except Exception:
    _parser = None

pytestmark = pytest.mark.skipif(_parser is None, reason="tree-sitter grammar unavailable")

from understand_core.plugins.extractors.csharp_extractor import CSharpExtractor


def _parse(code: str):
    return parse_source(_parser, code)


extractor = CSharpExtractor()


def test_has_correct_language_ids():
    assert extractor.language_ids == ["csharp"]


# ---- functions (methods & constructors) ----


def test_extracts_methods_with_params_and_return_types():
    root = _parse(
        """namespace App {
    public class Foo {
        public string GetName(int id) {
            return "";
        }
        private void Process(string data, int count) {
        }
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 2

    assert result["functions"][0]["name"] == "GetName"
    assert result["functions"][0]["params"] == ["id"]
    assert result["functions"][0]["returnType"] == "string"

    assert result["functions"][1]["name"] == "Process"
    assert result["functions"][1]["params"] == ["data", "count"]
    assert result["functions"][1]["returnType"] == "void"


def test_extracts_constructors():
    root = _parse(
        """namespace App {
    public class Foo {
        public Foo(string name, int value) {
            this.name = name;
        }
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
        """namespace App {
    public class Foo {
        public void Run() {}
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "Run"
    assert result["functions"][0]["params"] == []
    assert result["functions"][0]["returnType"] == "void"


def test_extracts_methods_with_generic_return_types():
    root = _parse(
        """namespace App {
    public class Foo {
        public List<string> GetItems() {
            return null;
        }
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "GetItems"
    assert result["functions"][0]["returnType"] == "List<string>"


def test_reports_correct_line_ranges_for_multi_line_methods():
    root = _parse(
        """namespace App {
    public class Foo {
        public int Calculate(
            int a,
            int b
        ) {
            int result = a + b;
            return result;
        }
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["functions"]) == 1
    assert result["functions"][0]["lineRange"][0] == 3
    assert result["functions"][0]["lineRange"][1] == 9


# ---- classes ----


def test_extracts_class_with_methods_properties_and_fields():
    root = _parse(
        """namespace App {
    public class Server {
        private string _host;
        private int _port;
        public string Address { get; set; }
        public void Start() {}
        public void Stop() {}
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Server"
    assert result["classes"][0]["properties"] == ["_host", "_port", "Address"]
    assert result["classes"][0]["methods"] == ["Start", "Stop"]
    assert result["classes"][0]["lineRange"][0] == 2


def test_extracts_empty_class():
    root = _parse(
        """namespace App {
    public class Empty {
    }
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
        """namespace App {
    public class Foo {
        public Foo() {}
        public void Run() {}
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert result["classes"][0]["methods"] == ["Foo", "Run"]


# ---- interfaces ----


def test_extracts_interface_with_method_signatures():
    root = _parse(
        """namespace App {
    interface IRepository {
        List<User> FindAll();
        User FindById(int id);
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "IRepository"
    assert result["classes"][0]["methods"] == ["FindAll", "FindById"]
    assert result["classes"][0]["properties"] == []


def test_extracts_empty_interface():
    root = _parse(
        """namespace App {
    interface IMarker {
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "IMarker"
    assert result["classes"][0]["methods"] == []


# ---- imports (using directives) ----


def test_extracts_simple_using_directives():
    root = _parse(
        """using System;
namespace App {
    public class Foo {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 1
    assert result["imports"][0]["source"] == "System"
    assert result["imports"][0]["specifiers"] == ["System"]
    assert result["imports"][0]["lineNumber"] == 1


def test_extracts_qualified_using_directives():
    root = _parse(
        """using System;
using System.Collections.Generic;
namespace App {
    public class Foo {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "System"
    assert result["imports"][0]["specifiers"] == ["System"]
    assert result["imports"][0]["lineNumber"] == 1
    assert result["imports"][1]["source"] == "System.Collections.Generic"
    assert result["imports"][1]["specifiers"] == ["Generic"]
    assert result["imports"][1]["lineNumber"] == 2


def test_reports_correct_import_line_numbers_with_gaps():
    root = _parse(
        """using System;

using System.Linq;
namespace App {
    public class Foo {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert result["imports"][0]["lineNumber"] == 1
    assert result["imports"][1]["lineNumber"] == 3


# ---- exports ----


def test_exports_public_class_methods_constructor_and_properties():
    root = _parse(
        """namespace App {
    public class UserService {
        private string _name;
        public int MaxRetries { get; set; }
        public UserService(string name) {
            _name = name;
        }
        public void Start() {}
        private void Helper() {}
    }
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "UserService" in export_names  # class
    user_service_exports = [e for e in result["exports"] if e["name"] == "UserService"]
    assert len(user_service_exports) == 2  # class + constructor
    assert "MaxRetries" in export_names  # public property
    assert "Start" in export_names
    assert "Helper" not in export_names
    assert "_name" not in export_names  # private field


def test_does_not_export_non_public_classes():
    root = _parse(
        """namespace App {
    class Internal {
        void Run() {}
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["exports"]) == 0


def test_exports_public_fields():
    root = _parse(
        """namespace App {
    public class Config {
        public string ApiKey;
        private int _retries;
    }
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "Config" in export_names
    assert "ApiKey" in export_names
    assert "_retries" not in export_names


def test_exports_public_interface():
    root = _parse(
        """namespace App {
    public interface IRepository {
        void Save();
    }
}
"""
    )
    result = extractor.extract_structure(root)

    export_names = [e["name"] for e in result["exports"]]
    assert "IRepository" in export_names


# ---- Call Graph ----


def test_extracts_simple_method_calls():
    root = _parse(
        """namespace App {
    public class Foo {
        public void Process(int data) {
            Transform(data);
            Format(data);
        }
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["caller"] == "Process"
    assert result[0]["callee"] == "Transform"
    assert result[1]["caller"] == "Process"
    assert result[1]["callee"] == "Format"


def test_extracts_qualified_method_calls():
    root = _parse(
        """namespace App {
    public class Foo {
        private void Log(string message) {
            Console.WriteLine(message);
        }
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "Log"
    assert result[0]["callee"] == "Console.WriteLine"


def test_extracts_object_creation_expressions():
    root = _parse(
        """namespace App {
    public class Foo {
        public void Create() {
            var b = new Bar();
        }
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "Create"
    assert result[0]["callee"] == "new Bar"


def test_tracks_correct_caller_for_constructors():
    root = _parse(
        """namespace App {
    public class Foo {
        public Foo() {
            Init();
        }
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 1
    assert result[0]["caller"] == "Foo"
    assert result[0]["callee"] == "Init"


def test_reports_correct_line_numbers_for_calls():
    root = _parse(
        """namespace App {
    public class Foo {
        public void Run() {
            Foo();
            Bar();
        }
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 2
    assert result[0]["lineNumber"] == 4
    assert result[1]["lineNumber"] == 5


def test_ignores_calls_outside_methods():
    root = _parse(
        """namespace App {
    public class Foo {
        private string _value = String.Empty;
    }
}
"""
    )
    result = extractor.extract_call_graph(root)

    assert len(result) == 0


# ---- namespace handling ----


def test_extracts_declarations_from_block_scoped_namespace():
    root = _parse(
        """namespace App.Services {
    public class Svc {
        public void Run() {}
    }
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Svc"
    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "Run"


def test_extracts_declarations_alongside_file_scoped_namespace():
    root = _parse(
        """namespace App.Services;

public class Svc {
    public void Run() {}
}
"""
    )
    result = extractor.extract_structure(root)

    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Svc"
    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "Run"


# ---- comprehensive ----


def test_handles_a_realistic_csharp_module():
    root = _parse(
        """using System;
using System.Collections.Generic;

namespace App.Services
{
    public class UserService
    {
        private string _name;
        public int MaxRetries { get; set; }

        public UserService(string name)
        {
            _name = name;
        }

        public List<User> GetUsers(int limit)
        {
            return FetchFromDb(limit);
        }

        private void Log(string message)
        {
            Console.WriteLine(message);
        }
    }

    public interface IRepository
    {
        List<User> FindAll();
        User FindById(int id);
    }
}
"""
    )
    result = extractor.extract_structure(root)

    # Functions: UserService (constructor), GetUsers, Log
    assert len(result["functions"]) == 3
    assert sorted(f["name"] for f in result["functions"]) == sorted(
        ["GetUsers", "Log", "UserService"]
    )

    ctor = next((f for f in result["functions"] if f["name"] == "UserService"), None)
    assert ctor["params"] == ["name"]
    assert ctor["returnType"] is None

    get_users = next((f for f in result["functions"] if f["name"] == "GetUsers"), None)
    assert get_users["params"] == ["limit"]
    assert get_users["returnType"] == "List<User>"

    log = next((f for f in result["functions"] if f["name"] == "Log"), None)
    assert log["params"] == ["message"]
    assert log["returnType"] == "void"

    # Classes: UserService, IRepository
    assert len(result["classes"]) == 2

    user_service = next((c for c in result["classes"] if c["name"] == "UserService"), None)
    assert user_service is not None
    assert sorted(user_service["methods"]) == sorted(["GetUsers", "Log", "UserService"])
    assert sorted(user_service["properties"]) == sorted(["MaxRetries", "_name"])

    repository = next((c for c in result["classes"] if c["name"] == "IRepository"), None)
    assert repository is not None
    assert repository["methods"] == ["FindAll", "FindById"]
    assert repository["properties"] == []

    # Imports
    assert len(result["imports"]) == 2
    assert result["imports"][0]["source"] == "System"
    assert result["imports"][0]["specifiers"] == ["System"]
    assert result["imports"][1]["source"] == "System.Collections.Generic"
    assert result["imports"][1]["specifiers"] == ["Generic"]

    # Exports
    export_names = [e["name"] for e in result["exports"]]
    assert "UserService" in export_names
    assert "GetUsers" in export_names
    assert "MaxRetries" in export_names
    assert "IRepository" in export_names
    assert "Log" not in export_names  # private
    assert "_name" not in export_names  # private field

    # Call graph
    calls = extractor.extract_call_graph(root)

    get_users_calls = [e for e in calls if e["caller"] == "GetUsers"]
    assert any(e["callee"] == "FetchFromDb" for e in get_users_calls)

    log_calls = [e for e in calls if e["caller"] == "Log"]
    assert any(e["callee"] == "Console.WriteLine" for e in log_calls)
