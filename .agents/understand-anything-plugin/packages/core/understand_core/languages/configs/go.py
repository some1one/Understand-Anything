"""Port of ``configs/go.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

go_config = LanguageConfig(
    id="go",
    displayName="Go",
    extensions=[".go"],
    treeSitter={
        "wasmPackage": "tree-sitter-go",
        "wasmFile": "tree-sitter-go.wasm",
    },
    concepts=["goroutines", "channels", "interfaces", "struct embedding", "error handling patterns", "defer/panic/recover", "slices", "pointers", "concurrency patterns"],
    filePatterns={
        "entryPoints": ["main.go", "cmd/*/main.go"],
        "barrels": [],
        "tests": ["*_test.go"],
        "config": ["go.mod", "go.sum"],
    },
)
