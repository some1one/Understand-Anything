"""Port of ``configs/c.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

c_config = LanguageConfig(
    id="c",
    displayName="C",
    extensions=[".c", ".h"],
    treeSitter={
        "wasmPackage": "tree-sitter-cpp",
        "wasmFile": "tree-sitter-cpp.wasm",
    },
    concepts=["pointers", "manual memory management", "structs", "unions", "function pointers", "preprocessor macros", "header files", "static vs dynamic linking"],
    filePatterns={
        "entryPoints": ["main.c", "src/main.c"],
        "barrels": [],
        "tests": ["*_test.c", "test_*.c"],
        "config": ["Makefile", "CMakeLists.txt", "meson.build"],
    },
)
