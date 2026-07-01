"""Port of ``configs/lua.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

lua_config = LanguageConfig(
    id="lua",
    displayName="Lua",
    extensions=[".lua"],
    concepts=["tables", "metatables", "coroutines", "closures", "prototype-based OOP", "varargs", "weak references", "environments"],
    filePatterns={
        "entryPoints": ["main.lua", "init.lua"],
        "barrels": [],
        "tests": ["*_test.lua", "test_*.lua", "*_spec.lua"],
        "config": [".luacheckrc", "rockspec"],
    },
)
