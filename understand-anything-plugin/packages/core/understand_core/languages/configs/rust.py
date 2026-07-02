"""Port of ``configs/rust.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

rust_config = LanguageConfig(
    id="rust",
    displayName="Rust",
    extensions=[".rs"],
    treeSitter={
        "wasmPackage": "tree-sitter-rust",
        "wasmFile": "tree-sitter-rust.wasm",
    },
    concepts=["ownership", "borrowing", "lifetimes", "traits", "pattern matching", "enums with data", "error handling (Result/Option)", "macros", "async/await", "unsafe blocks", "generics", "closures"],
    filePatterns={
        "entryPoints": ["src/main.rs", "src/lib.rs"],
        "barrels": ["mod.rs", "lib.rs"],
        "tests": ["tests/*.rs"],
        "config": ["Cargo.toml"],
    },
)
