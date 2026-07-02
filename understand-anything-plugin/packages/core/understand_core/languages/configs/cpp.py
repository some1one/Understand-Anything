"""Port of ``configs/cpp.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

cpp_config = LanguageConfig(
    id="cpp",
    displayName="C++",
    extensions=[".cpp", ".cc", ".cxx", ".hpp", ".hxx"],
    treeSitter={
        "wasmPackage": "tree-sitter-cpp",
        "wasmFile": "tree-sitter-cpp.wasm",
    },
    concepts=["templates", "RAII", "smart pointers", "move semantics", "operator overloading", "virtual functions", "namespaces", "constexpr", "lambda expressions", "STL containers"],
    filePatterns={
        "entryPoints": ["main.cpp", "src/main.cpp"],
        "barrels": [],
        "tests": ["*_test.cpp", "*_test.cc", "test_*.cpp"],
        "config": ["CMakeLists.txt", "Makefile", "meson.build"],
    },
)
