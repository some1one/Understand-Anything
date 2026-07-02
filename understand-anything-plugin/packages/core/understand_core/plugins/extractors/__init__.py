"""Language extractors. Mirrors ``plugins/extractors/index.ts``."""

from __future__ import annotations

from understand_core.plugins.extractors.base_extractor import (
    find_child,
    find_children,
    get_string_value,
    has_child_of_type,
    node_text,
    traverse,
)
from understand_core.plugins.extractors.cpp_extractor import CppExtractor
from understand_core.plugins.extractors.csharp_extractor import CSharpExtractor
from understand_core.plugins.extractors.dart_extractor import DartExtractor
from understand_core.plugins.extractors.go_extractor import GoExtractor
from understand_core.plugins.extractors.java_extractor import JavaExtractor
from understand_core.plugins.extractors.kotlin_extractor import KotlinExtractor
from understand_core.plugins.extractors.php_extractor import PhpExtractor
from understand_core.plugins.extractors.python_extractor import PythonExtractor
from understand_core.plugins.extractors.ruby_extractor import RubyExtractor
from understand_core.plugins.extractors.rust_extractor import RustExtractor
from understand_core.plugins.extractors.types import LanguageExtractor, TreeSitterNode
from understand_core.plugins.extractors.typescript_extractor import TypeScriptExtractor

__all__ = [
    "LanguageExtractor",
    "TreeSitterNode",
    "traverse",
    "get_string_value",
    "find_child",
    "find_children",
    "has_child_of_type",
    "node_text",
    "TypeScriptExtractor",
    "PythonExtractor",
    "GoExtractor",
    "RustExtractor",
    "JavaExtractor",
    "RubyExtractor",
    "PhpExtractor",
    "CppExtractor",
    "CSharpExtractor",
    "DartExtractor",
    "KotlinExtractor",
    "builtin_extractors",
]

# Order mirrors builtinExtractors in index.ts.
builtin_extractors: list[LanguageExtractor] = [
    TypeScriptExtractor(),
    PythonExtractor(),
    GoExtractor(),
    RustExtractor(),
    JavaExtractor(),
    RubyExtractor(),
    PhpExtractor(),
    CppExtractor(),
    CSharpExtractor(),
    DartExtractor(),
    KotlinExtractor(),
]
