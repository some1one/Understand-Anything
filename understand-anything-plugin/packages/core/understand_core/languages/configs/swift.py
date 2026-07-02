"""Port of ``configs/swift.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

swift_config = LanguageConfig(
    id="swift",
    displayName="Swift",
    extensions=[".swift"],
    concepts=["optionals", "protocols", "extensions", "generics", "closures", "property wrappers", "result builders", "actors", "structured concurrency", "value types vs reference types"],
    filePatterns={
        "entryPoints": ["Sources/*/main.swift", "App.swift", "AppDelegate.swift"],
        "barrels": [],
        "tests": ["*Tests.swift", "Tests/**/*.swift"],
        "config": ["Package.swift"],
    },
)
