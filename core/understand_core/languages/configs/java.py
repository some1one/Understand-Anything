"""Port of ``configs/java.ts``."""

from __future__ import annotations

from ..types import LanguageConfig

java_config = LanguageConfig(
    id="java",
    displayName="Java",
    extensions=[".java"],
    treeSitter={
        "wasmPackage": "tree-sitter-java",
        "wasmFile": "tree-sitter-java.wasm",
    },
    concepts=["generics", "annotations", "interfaces", "abstract classes", "streams API", "lambdas", "sealed classes", "records", "dependency injection", "checked exceptions"],
    filePatterns={
        "entryPoints": ["**/Application.java", "**/Main.java", "src/main/java/**/App.java"],
        "barrels": [],
        "tests": ["*Test.java", "*Tests.java", "*IT.java"],
        "config": ["pom.xml", "build.gradle", "build.gradle.kts"],
    },
)
