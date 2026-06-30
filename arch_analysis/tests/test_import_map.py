"""Port of tests/skill/understand/test_extract_import_map.test.mjs.

Each JS ``it(...)`` is mirrored as a Python test. We call ``extract_import_map``
directly (no subprocess) and capture warnings via ``capsys`` (the script writes
warnings/stats to stderr).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from arch_analysis.extract_import_map import extract_import_map


def setup_tree(root: Path, files: dict[str, str]) -> None:
    for rel_path, contents in files.items():
        abs_path = root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(contents, encoding="utf-8")


def run(root: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    return extract_import_map({"projectRoot": str(root), "files": files})


# ---------------------------------------------------------------------------
# TypeScript / JavaScript resolver
# ---------------------------------------------------------------------------


def test_ts_relative_imports_with_extension_probes(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.ts": "import { foo } from './utils';\nimport cfg from './config';\nfoo(cfg);\n",
            "src/utils.ts": "export function foo(x: unknown) { return x; }\n",
            "src/config.ts": "export default { debug: true };\n",
            "README.md": "# project\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/utils.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/config.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "README.md", "language": "markdown", "fileCategory": "docs"},
        ],
    )
    assert out["scriptCompleted"] is True
    assert out["importMap"]["src/index.ts"] == ["src/config.ts", "src/utils.ts"]
    assert out["importMap"]["src/utils.ts"] == []
    assert out["importMap"]["README.md"] == []
    assert out["stats"]["filesScanned"] == 4
    assert out["stats"]["filesWithImports"] == 1
    assert out["stats"]["totalEdges"] == 2


def test_tsconfig_paths_aliases(tmp_path):
    setup_tree(
        tmp_path,
        {
            "tsconfig.json": json.dumps(
                {
                    "compilerOptions": {
                        "baseUrl": ".",
                        "paths": {"@/*": ["src/*"], "~lib/*": ["src/lib/*"]},
                    }
                }
            ),
            "src/index.ts": "import { greet } from '@/utils/greet';\nimport { add } from '~lib/math';\n",
            "src/utils/greet.ts": "export function greet(name: string) { return 'hi ' + name; }\n",
            "src/lib/math.ts": "export const add = (a: number, b: number) => a + b;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/utils/greet.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/lib/math.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.ts"] == ["src/lib/math.ts", "src/utils/greet.ts"]


def test_index_barrel_imports(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.ts": "import { thing } from './stuff';\n",
            "src/stuff/index.ts": "export const thing = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/stuff/index.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.ts"] == ["src/stuff/index.ts"]


def test_drops_external_package_imports(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.ts": "import express from 'express';\nimport { z } from 'zod';\nimport { foo } from './local';\n",
            "src/local.ts": "export const foo = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/local.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.ts"] == ["src/local.ts"]


def test_javascript_require_calls(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.js": "const cfg = require('./config');\nconst utils = require('../shared/utils');\n",
            "src/config.js": "module.exports = { x: 1 };\n",
            "shared/utils.js": "module.exports = { y: 2 };\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.js", "language": "javascript", "fileCategory": "code"},
            {"path": "src/config.js", "language": "javascript", "fileCategory": "code"},
            {"path": "shared/utils.js", "language": "javascript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.js"] == ["shared/utils.js", "src/config.js"]


def test_per_package_tsconfig_no_cross_leakage(tmp_path):
    setup_tree(
        tmp_path,
        {
            "packages/foo/tsconfig.json": json.dumps(
                {"compilerOptions": {"baseUrl": ".", "paths": {"@foo/*": ["src/*"]}}}
            ),
            "packages/foo/src/x.ts": "import { y } from '@foo/y';\nexport const x = y;\n",
            "packages/foo/src/y.ts": "export const y = 1;\n",
            "packages/bar/tsconfig.json": json.dumps(
                {"compilerOptions": {"baseUrl": ".", "paths": {"@bar/*": ["src/*"]}}}
            ),
            "packages/bar/src/x.ts": "import { y } from '@bar/y';\nimport { fy } from '@foo/y';\nexport const x = y;\n",
            "packages/bar/src/y.ts": "export const y = 2;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "packages/foo/tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "packages/foo/src/x.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "packages/foo/src/y.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "packages/bar/tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "packages/bar/src/x.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "packages/bar/src/y.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["packages/foo/src/x.ts"] == ["packages/foo/src/y.ts"]
    assert out["importMap"]["packages/bar/src/x.ts"] == ["packages/bar/src/y.ts"]
    assert "packages/foo/src/y.ts" not in out["importMap"]["packages/bar/src/x.ts"]


@pytest.mark.parametrize(
    "tsconfig,index_src,expected",
    [
        ({"compilerOptions": {"paths": {"@/*": ["./*"]}}}, "import { x } from '@/lib/thing';\nconst _ = x;\n", "lib/thing.ts"),
        ({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]}}}, "import { x } from '@/lib/thing';\nconst _ = x;\n", "lib/thing.ts"),
    ],
)
def test_tsconfig_leading_dotslash_root(tmp_path, tsconfig, index_src, expected):
    setup_tree(
        tmp_path,
        {
            "tsconfig.json": json.dumps(tsconfig),
            "src/app.ts": index_src,
            "lib/thing.ts": "export const x = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "src/app.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "lib/thing.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert expected in out["importMap"]["src/app.ts"]


def test_tsconfig_leading_dotslash_baseurl_src(tmp_path):
    setup_tree(
        tmp_path,
        {
            "tsconfig.json": json.dumps(
                {"compilerOptions": {"baseUrl": "src", "paths": {"@/*": ["./*"]}}}
            ),
            "src/app.ts": "import { x } from '@/thing';\nconst _ = x;\n",
            "src/thing.ts": "export const x = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "src/app.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/thing.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert "src/thing.ts" in out["importMap"]["src/app.ts"]


def test_tsconfig_bare_star_target(tmp_path):
    setup_tree(
        tmp_path,
        {
            "tsconfig.json": json.dumps({"compilerOptions": {"paths": {"@/*": ["*"]}}}),
            "src/app.ts": "import { x } from '@/lib/thing';\nconst _ = x;\n",
            "lib/thing.ts": "export const x = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "src/app.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "lib/thing.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert "lib/thing.ts" in out["importMap"]["src/app.ts"]


def test_nodenext_js_to_ts(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.ts": "import { resolveBackend } from './llm-backend-selector.js';\nimport { loadConfig } from './config.js';\n",
            "src/llm-backend-selector.ts": "export function resolveBackend() {}\n",
            "src/config.ts": "export function loadConfig() {}\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/llm-backend-selector.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/config.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.ts"] == ["src/config.ts", "src/llm-backend-selector.ts"]


def test_nodenext_jsx_mjs_rewrites(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.ts": "import Comp from './Comp.jsx';\nimport { fn } from './worker.mjs';\n",
            "src/Comp.tsx": "export default function Comp() {}\n",
            "src/worker.mts": "export function fn() {}\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/Comp.tsx", "language": "typescript", "fileCategory": "code"},
            {"path": "src/worker.mts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.ts"] == ["src/Comp.tsx", "src/worker.mts"]


def test_resolves_to_js_when_both_exist(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.ts": "import { x } from './config.js';\n",
            "src/config.ts": "export const x = 1;\n",
            "src/config.js": "export const x = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/config.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/config.js", "language": "javascript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.ts"] == ["src/config.js"]


def test_traditional_js_to_js(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.js": "import { x } from './util.js';\n",
            "src/util.js": "export const x = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.js", "language": "javascript", "fileCategory": "code"},
            {"path": "src/util.js", "language": "javascript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.js"] == ["src/util.js"]


def test_no_extension_probe(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.ts": "import { foo } from './utils';\n",
            "src/utils.ts": "export function foo() {}\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/utils.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.ts"] == ["src/utils.ts"]


def test_js_import_missing_ts_source(tmp_path):
    setup_tree(tmp_path, {"src/index.ts": "import './completely-missing.js';\n"})
    out = run(
        tmp_path,
        [{"path": "src/index.ts", "language": "typescript", "fileCategory": "code"}],
    )
    assert out["importMap"]["src/index.ts"] == []


# ---------------------------------------------------------------------------
# Python resolver
# ---------------------------------------------------------------------------


def test_python_relative_imports(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/app.py": "from . import helpers\nfrom .utils import shout\nfrom ..core import boot\n",
            "src/helpers.py": "def help(): pass\n",
            "src/utils.py": "def shout(): pass\n",
            "core.py": "def boot(): pass\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/app.py", "language": "python", "fileCategory": "code"},
            {"path": "src/helpers.py", "language": "python", "fileCategory": "code"},
            {"path": "src/utils.py", "language": "python", "fileCategory": "code"},
            {"path": "core.py", "language": "python", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/app.py"] == ["core.py", "src/helpers.py", "src/utils.py"]


def test_python_from_dot_namespace_package(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/svc/main.py": "from . import helpers, util\nfrom . import nested\n",
            "src/svc/helpers.py": "def help(): pass\n",
            "src/svc/util.py": "def u(): pass\n",
            "src/svc/nested/__init__.py": "# package\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/svc/main.py", "language": "python", "fileCategory": "code"},
            {"path": "src/svc/helpers.py", "language": "python", "fileCategory": "code"},
            {"path": "src/svc/util.py", "language": "python", "fileCategory": "code"},
            {"path": "src/svc/nested/__init__.py", "language": "python", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/svc/main.py"] == [
        "src/svc/helpers.py",
        "src/svc/nested/__init__.py",
        "src/svc/util.py",
    ]


def test_python_absolute_and_init(tmp_path):
    setup_tree(
        tmp_path,
        {
            "main.py": "import src.utils.formatter\nfrom src.utils import formatter\nfrom src import config\n",
            "src/__init__.py": "",
            "src/utils/__init__.py": "",
            "src/utils/formatter.py": "def fmt(): pass\n",
            "src/config.py": "DEBUG = True\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "main.py", "language": "python", "fileCategory": "code"},
            {"path": "src/__init__.py", "language": "python", "fileCategory": "code"},
            {"path": "src/utils/__init__.py", "language": "python", "fileCategory": "code"},
            {"path": "src/utils/formatter.py", "language": "python", "fileCategory": "code"},
            {"path": "src/config.py", "language": "python", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["main.py"] == [
        "src/__init__.py",
        "src/config.py",
        "src/utils/__init__.py",
        "src/utils/formatter.py",
    ]


def test_python_drops_external(tmp_path):
    setup_tree(
        tmp_path,
        {
            "app.py": "import os\nimport sys\nimport requests\nfrom datetime import datetime\nfrom .local import thing\n",
            "local.py": "thing = 1\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "app.py", "language": "python", "fileCategory": "code"},
            {"path": "local.py", "language": "python", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["app.py"] == ["local.py"]


def test_python_per_service_root(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/svc_a/main.py": "import helpers\nfrom helpers import shout\n",
            "src/svc_a/helpers.py": "def shout(): pass\n",
            "src/svc_b/main.py": "import helpers\nfrom helpers import shout\n",
            "src/svc_b/helpers.py": "def shout(): pass\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/svc_a/main.py", "language": "python", "fileCategory": "code"},
            {"path": "src/svc_a/helpers.py", "language": "python", "fileCategory": "code"},
            {"path": "src/svc_b/main.py", "language": "python", "fileCategory": "code"},
            {"path": "src/svc_b/helpers.py", "language": "python", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/svc_a/main.py"] == ["src/svc_a/helpers.py"]
    assert "src/svc_b/helpers.py" not in out["importMap"]["src/svc_a/main.py"]
    assert out["importMap"]["src/svc_b/main.py"] == ["src/svc_b/helpers.py"]
    assert "src/svc_a/helpers.py" not in out["importMap"]["src/svc_b/main.py"]


# ---------------------------------------------------------------------------
# Go resolver
# ---------------------------------------------------------------------------


def test_go_strip_module_prefix(tmp_path):
    setup_tree(
        tmp_path,
        {
            "go.mod": "module github.com/foo/bar\n\ngo 1.21\n",
            "main.go": 'package main\n\nimport (\n\t"fmt"\n\t"github.com/foo/bar/util"\n\t"github.com/foo/bar/db"\n)\n\nfunc main() {\n\tfmt.Println(util.Hi())\n\tdb.Connect()\n}\n',
            "util/hello.go": 'package util\n\nfunc Hi() string { return "hi" }\n',
            "util/world.go": 'package util\n\nfunc World() string { return "world" }\n',
            "db/db.go": "package db\n\nfunc Connect() {}\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "go.mod", "language": "config", "fileCategory": "config"},
            {"path": "main.go", "language": "go", "fileCategory": "code"},
            {"path": "util/hello.go", "language": "go", "fileCategory": "code"},
            {"path": "util/world.go", "language": "go", "fileCategory": "code"},
            {"path": "db/db.go", "language": "go", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["main.go"] == ["db/db.go", "util/hello.go", "util/world.go"]


def test_go_multi_module(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/a/go.mod": "module github.com/org/a\n\ngo 1.21\n",
            "src/a/main.go": 'package main\n\nimport (\n\t"github.com/org/a/sub"\n\t"github.com/org/b/sub"\n)\n\nfunc main() { sub.X() }\n',
            "src/a/sub/sub.go": "package sub\n\nfunc X() {}\n",
            "src/b/go.mod": "module github.com/org/b\n\ngo 1.21\n",
            "src/b/main.go": 'package main\n\nimport (\n\t"github.com/org/b/sub"\n)\n\nfunc main() { sub.Y() }\n',
            "src/b/sub/sub.go": "package sub\n\nfunc Y() {}\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/a/go.mod", "language": "config", "fileCategory": "config"},
            {"path": "src/a/main.go", "language": "go", "fileCategory": "code"},
            {"path": "src/a/sub/sub.go", "language": "go", "fileCategory": "code"},
            {"path": "src/b/go.mod", "language": "config", "fileCategory": "config"},
            {"path": "src/b/main.go", "language": "go", "fileCategory": "code"},
            {"path": "src/b/sub/sub.go", "language": "go", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/a/main.go"] == ["src/a/sub/sub.go"]
    assert out["importMap"]["src/b/main.go"] == ["src/b/sub/sub.go"]


def test_go_no_ancestor_gomod_warning(tmp_path, capsys):
    setup_tree(
        tmp_path,
        {
            "orphan/main.go": 'package main\n\nimport (\n\t"github.com/foo/bar/util"\n\t"github.com/foo/bar/db"\n)\n\nfunc main() {}\n',
        },
    )
    out = run(
        tmp_path,
        [{"path": "orphan/main.go", "language": "go", "fileCategory": "code"}],
    )
    assert out["importMap"]["orphan/main.go"] == []
    stderr = capsys.readouterr().err
    go_warnings = [l for l in stderr.split("\n") if "no ancestor go.mod" in l]
    assert len(go_warnings) == 1
    assert "Go file orphan/main.go has no ancestor go.mod" in go_warnings[0]
    assert "module-prefix imports skipped" in go_warnings[0]


# ---------------------------------------------------------------------------
# Java resolver
# ---------------------------------------------------------------------------


def test_java_dotted_suffix_probe(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/main/java/com/example/App.java": "package com.example;\n\nimport com.example.foo.Bar;\nimport com.example.util.Helper;\n\npublic class App { }\n",
            "src/main/java/com/example/foo/Bar.java": "package com.example.foo;\n\npublic class Bar { }\n",
            "src/main/java/com/example/util/Helper.java": "package com.example.util;\n\npublic class Helper { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/main/java/com/example/App.java", "language": "java", "fileCategory": "code"},
            {"path": "src/main/java/com/example/foo/Bar.java", "language": "java", "fileCategory": "code"},
            {"path": "src/main/java/com/example/util/Helper.java", "language": "java", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/main/java/com/example/App.java"] == [
        "src/main/java/com/example/foo/Bar.java",
        "src/main/java/com/example/util/Helper.java",
    ]


def test_java_drops_external(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/x/App.java": "package x;\nimport java.util.List;\nimport java.io.IOException;\nimport x.Local;\npublic class App { }\n",
            "src/x/Local.java": "package x;\npublic class Local { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/x/App.java", "language": "java", "fileCategory": "code"},
            {"path": "src/x/Local.java", "language": "java", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/x/App.java"] == ["src/x/Local.java"]


# ---------------------------------------------------------------------------
# Kotlin resolver
# ---------------------------------------------------------------------------


def test_kotlin_dotted_suffix_probe(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/main/kotlin/com/example/Main.kt": "package com.example\n\nimport com.example.foo.Bar\nimport com.example.util.Helper\n\nfun main() { }\n",
            "src/main/kotlin/com/example/foo/Bar.kt": "package com.example.foo\n\nclass Bar\n",
            "src/main/kotlin/com/example/util/Helper.kt": "package com.example.util\n\nobject Helper\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/main/kotlin/com/example/Main.kt", "language": "kotlin", "fileCategory": "code"},
            {"path": "src/main/kotlin/com/example/foo/Bar.kt", "language": "kotlin", "fileCategory": "code"},
            {"path": "src/main/kotlin/com/example/util/Helper.kt", "language": "kotlin", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/main/kotlin/com/example/Main.kt"] == [
        "src/main/kotlin/com/example/foo/Bar.kt",
        "src/main/kotlin/com/example/util/Helper.kt",
    ]


def test_kotlin_no_phantom_resolve(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/Main.kt": "package com.example\n\nimport ...\nimport .foo\nimport com.example.real.Bar\n",
            "src/com/example/real/Bar.kt": "package com.example.real\nclass Bar\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/Main.kt", "language": "kotlin", "fileCategory": "code"},
            {"path": "src/com/example/real/Bar.kt", "language": "kotlin", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/Main.kt"] == ["src/com/example/real/Bar.kt"]


# ---------------------------------------------------------------------------
# C# resolver
# ---------------------------------------------------------------------------


def test_csharp_using_dotted_suffix_probe(tmp_path):
    setup_tree(
        tmp_path,
        {
            "Program.cs": "using System;\nusing MyApp.Util.Helper;\nusing MyApp.Models.User;\n\nnamespace MyApp { class Program { } }\n",
            "MyApp/Util/Helper.cs": "namespace MyApp.Util { public class Helper { } }\n",
            "MyApp/Models/User.cs": "namespace MyApp.Models { public class User { } }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "Program.cs", "language": "csharp", "fileCategory": "code"},
            {"path": "MyApp/Util/Helper.cs", "language": "csharp", "fileCategory": "code"},
            {"path": "MyApp/Models/User.cs", "language": "csharp", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["Program.cs"] == [
        "MyApp/Models/User.cs",
        "MyApp/Util/Helper.cs",
    ]


# ---------------------------------------------------------------------------
# Ruby resolver
# ---------------------------------------------------------------------------


def test_ruby_require_probes(tmp_path):
    setup_tree(
        tmp_path,
        {
            "app/controllers/users_controller.rb": "require_relative '../helpers/auth'\nrequire 'shared/logger'\nrequire 'json'\n\nclass UsersController\nend\n",
            "app/helpers/auth.rb": "module Auth\nend\n",
            "lib/shared/logger.rb": "module Shared\n  module Logger\n  end\nend\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "app/controllers/users_controller.rb", "language": "ruby", "fileCategory": "code"},
            {"path": "app/helpers/auth.rb", "language": "ruby", "fileCategory": "code"},
            {"path": "lib/shared/logger.rb", "language": "ruby", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["app/controllers/users_controller.rb"] == [
        "app/helpers/auth.rb",
        "lib/shared/logger.rb",
    ]


# ---------------------------------------------------------------------------
# PHP resolver
# ---------------------------------------------------------------------------


def test_php_psr4_autoload(tmp_path):
    setup_tree(
        tmp_path,
        {
            "composer.json": json.dumps(
                {"autoload": {"psr-4": {"App\\": "src/", "App\\Tests\\": "tests/"}}}
            ),
            "src/Http/Controller.php": "<?php\nnamespace App\\Http;\n\nuse App\\Models\\User;\nuse App\\Util\\Logger;\nuse Symfony\\Component\\HttpFoundation\\Request;\n\nclass Controller { }\n",
            "src/Models/User.php": "<?php\nnamespace App\\Models;\nclass User { }\n",
            "src/Util/Logger.php": "<?php\nnamespace App\\Util;\nclass Logger { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "composer.json", "language": "json", "fileCategory": "config"},
            {"path": "src/Http/Controller.php", "language": "php", "fileCategory": "code"},
            {"path": "src/Models/User.php", "language": "php", "fileCategory": "code"},
            {"path": "src/Util/Logger.php", "language": "php", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/Http/Controller.php"] == [
        "src/Models/User.php",
        "src/Util/Logger.php",
    ]


def test_php_per_package_no_leakage(tmp_path):
    setup_tree(
        tmp_path,
        {
            "packages/foo/composer.json": json.dumps(
                {"autoload": {"psr-4": {"App\\Foo\\": "src/"}}}
            ),
            "packages/foo/src/X.php": "<?php\nnamespace App\\Foo;\n\nuse App\\Foo\\Y;\nuse App\\Bar\\Z;\nclass X { }\n",
            "packages/foo/src/Y.php": "<?php\nnamespace App\\Foo;\nclass Y { }\n",
            "packages/bar/composer.json": json.dumps(
                {"autoload": {"psr-4": {"App\\Bar\\": "src/"}}}
            ),
            "packages/bar/src/Z.php": "<?php\nnamespace App\\Bar;\nclass Z { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "packages/foo/composer.json", "language": "json", "fileCategory": "config"},
            {"path": "packages/foo/src/X.php", "language": "php", "fileCategory": "code"},
            {"path": "packages/foo/src/Y.php", "language": "php", "fileCategory": "code"},
            {"path": "packages/bar/composer.json", "language": "json", "fileCategory": "config"},
            {"path": "packages/bar/src/Z.php", "language": "php", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["packages/foo/src/X.php"] == ["packages/foo/src/Y.php"]
    assert "packages/bar/src/Z.php" not in out["importMap"]["packages/foo/src/X.php"]


def test_php_psr4_empty_prefix_fallback(tmp_path):
    setup_tree(
        tmp_path,
        {
            "composer.json": json.dumps({"autoload": {"psr-4": {"": "src/"}}}),
            "src/Foo/Bar.php": "<?php\nnamespace Foo;\n\nuse Foo\\Baz;\n\nclass Bar { }\n",
            "src/Foo/Baz.php": "<?php\nnamespace Foo;\nclass Baz { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "composer.json", "language": "json", "fileCategory": "config"},
            {"path": "src/Foo/Bar.php", "language": "php", "fileCategory": "code"},
            {"path": "src/Foo/Baz.php", "language": "php", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/Foo/Bar.php"] == ["src/Foo/Baz.php"]


# ---------------------------------------------------------------------------
# Rust resolver
# ---------------------------------------------------------------------------


def test_rust_use_crate_and_mod(tmp_path):
    setup_tree(
        tmp_path,
        {
            "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
            "src/lib.rs": "pub mod auth;\npub mod db;\n\nuse crate::auth::login;\nuse crate::db::query;\n\nfn boot() { login(); query(); }\n",
            "src/auth.rs": "pub fn login() { }\n",
            "src/db.rs": "pub fn query() { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "Cargo.toml", "language": "toml", "fileCategory": "config"},
            {"path": "src/lib.rs", "language": "rust", "fileCategory": "code"},
            {"path": "src/auth.rs", "language": "rust", "fileCategory": "code"},
            {"path": "src/db.rs", "language": "rust", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/lib.rs"] == ["src/auth.rs", "src/db.rs"]


def test_rust_super(tmp_path):
    setup_tree(
        tmp_path,
        {
            "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\n',
            "src/lib.rs": "pub mod inner;\npub mod sibling;\n",
            "src/sibling.rs": "pub fn hi() { }\n",
            "src/inner/mod.rs": "use super::sibling::hi;\nfn boot() { hi(); }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "Cargo.toml", "language": "toml", "fileCategory": "config"},
            {"path": "src/lib.rs", "language": "rust", "fileCategory": "code"},
            {"path": "src/sibling.rs", "language": "rust", "fileCategory": "code"},
            {"path": "src/inner/mod.rs", "language": "rust", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/inner/mod.rs"] == ["src/sibling.rs"]


# ---------------------------------------------------------------------------
# C / C++ resolver
# ---------------------------------------------------------------------------


def test_cpp_include_probes(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/main.cpp": '#include <iostream>\n#include "util.h"\n#include "helpers/log.h"\n\nint main() { return 0; }\n',
            "src/util.h": "#ifndef UTIL_H\n#define UTIL_H\nvoid util();\n#endif\n",
            "src/helpers/log.h": "#pragma once\nvoid log_msg(const char*);\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/main.cpp", "language": "cpp", "fileCategory": "code"},
            {"path": "src/util.h", "language": "cpp", "fileCategory": "code"},
            {"path": "src/helpers/log.h", "language": "cpp", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/main.cpp"] == ["src/helpers/log.h", "src/util.h"]


def test_c_include_project_level_fallback(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/app.c": '#include "config.h"\n#include "shared.h"\n\nint main() { return 0; }\n',
            "include/config.h": "#pragma once\n",
            "src/shared.h": "#pragma once\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/app.c", "language": "c", "fileCategory": "code"},
            {"path": "include/config.h", "language": "c", "fileCategory": "code"},
            {"path": "src/shared.h", "language": "c", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/app.c"] == ["include/config.h", "src/shared.h"]


# ---------------------------------------------------------------------------
# per-file failure resilience
# ---------------------------------------------------------------------------


def test_continues_when_file_missing(tmp_path, capsys):
    setup_tree(
        tmp_path,
        {
            "src/real.ts": "import { thing } from './other';\nexport const x = 1;\n",
            "src/other.ts": "export const thing = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/real.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/other.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/missing.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    assert out["scriptCompleted"] is True
    assert out["importMap"]["src/real.ts"] == ["src/other.ts"]
    assert out["importMap"]["src/other.ts"] == []
    assert out["importMap"]["src/missing.ts"] == []
    stderr = capsys.readouterr().err
    assert "import resolution failed for src/missing.ts" in stderr
    assert "importMap[src/missing.ts]=[]" in stderr


def test_stats_summary_via_cli(tmp_path):
    setup_tree(
        tmp_path,
        {"a.ts": "import { b } from './b';\n", "b.ts": "export const b = 1;\n"},
    )
    inp = {
        "projectRoot": str(tmp_path),
        "files": [
            {"path": "a.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "b.ts", "language": "typescript", "fileCategory": "code"},
        ],
    }
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.json"
    input_path.write_text(json.dumps(inp), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "arch_analysis.extract_import_map", str(input_path), str(output_path)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0
    assert "extract-import-map: filesScanned=2 filesWithImports=1 totalEdges=1" in result.stderr


# ---------------------------------------------------------------------------
# output schema invariants
# ---------------------------------------------------------------------------


def test_every_input_file_appears(tmp_path):
    setup_tree(
        tmp_path,
        {
            "a.ts": "// no imports\nexport const a = 1;\n",
            "README.md": "# x\n",
            "Dockerfile": "FROM node:22\n",
            "package.json": "{}\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "a.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "README.md", "language": "markdown", "fileCategory": "docs"},
            {"path": "Dockerfile", "language": "dockerfile", "fileCategory": "infra"},
            {"path": "package.json", "language": "json", "fileCategory": "config"},
        ],
    )
    assert sorted(out["importMap"].keys()) == [
        "Dockerfile", "README.md", "a.ts", "package.json",
    ]
    for arr in out["importMap"].values():
        assert isinstance(arr, list)


def test_deterministic_output(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/a.ts": "import { b } from './b';\nimport { c } from './c';\n",
            "src/b.ts": "export const b = 1;\n",
            "src/c.ts": "export const c = 2;\n",
        },
    )
    files = [
        {"path": "src/a.ts", "language": "typescript", "fileCategory": "code"},
        {"path": "src/b.ts", "language": "typescript", "fileCategory": "code"},
        {"path": "src/c.ts", "language": "typescript", "fileCategory": "code"},
    ]
    r1 = run(tmp_path, files)
    r2 = run(tmp_path, files)
    assert json.dumps(r1) == json.dumps(r2)


# ---------------------------------------------------------------------------
# regex comment-strip resilience
# ---------------------------------------------------------------------------


def test_js_require_in_comment_ignored(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/index.js": "// require('./fake');  <- commented out, must be ignored\n/* require('./alsofake'); also commented */\nconst real = require('./real');\n",
            "src/real.js": "module.exports = { x: 1 };\n",
            "src/fake.js": "module.exports = { fake: true };\n",
            "src/alsofake.js": "module.exports = { fake: true };\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/index.js", "language": "javascript", "fileCategory": "code"},
            {"path": "src/real.js", "language": "javascript", "fileCategory": "code"},
            {"path": "src/fake.js", "language": "javascript", "fileCategory": "code"},
            {"path": "src/alsofake.js", "language": "javascript", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/index.js"] == ["src/real.js"]


def test_ruby_require_in_comment_ignored(tmp_path):
    setup_tree(
        tmp_path,
        {
            "app.rb": "# require 'fake'  -- commented out, must be ignored\nrequire 'real'\n",
            "lib/real.rb": "module Real; end\n",
            "lib/fake.rb": "module Fake; end\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "app.rb", "language": "ruby", "fileCategory": "code"},
            {"path": "lib/real.rb", "language": "ruby", "fileCategory": "code"},
            {"path": "lib/fake.rb", "language": "ruby", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["app.rb"] == ["lib/real.rb"]


def test_rust_mod_in_comment_ignored(tmp_path):
    setup_tree(
        tmp_path,
        {
            "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\n',
            "src/lib.rs": "// mod fake_line;  <- commented out\n/* mod fake_block; */\npub mod real;\n",
            "src/real.rs": "pub fn r() { }\n",
            "src/fake_line.rs": "pub fn f() { }\n",
            "src/fake_block.rs": "pub fn f() { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "Cargo.toml", "language": "toml", "fileCategory": "config"},
            {"path": "src/lib.rs", "language": "rust", "fileCategory": "code"},
            {"path": "src/real.rs", "language": "rust", "fileCategory": "code"},
            {"path": "src/fake_line.rs", "language": "rust", "fileCategory": "code"},
            {"path": "src/fake_block.rs", "language": "rust", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/lib.rs"] == ["src/real.rs"]


# ---------------------------------------------------------------------------
# multi-source-root dotted FQN (Gradle/Maven)
# ---------------------------------------------------------------------------


def test_java_fqn_multiple_source_roots(tmp_path):
    setup_tree(
        tmp_path,
        {
            "src/main/java/com/example/App.java": "package com.example;\nimport com.foo.Bar;\npublic class App { }\n",
            "src/main/java/com/foo/Bar.java": "package com.foo;\npublic class Bar { }\n",
            "lib/src/main/java/com/foo/Bar.java": "package com.foo;\npublic class Bar { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "src/main/java/com/example/App.java", "language": "java", "fileCategory": "code"},
            {"path": "src/main/java/com/foo/Bar.java", "language": "java", "fileCategory": "code"},
            {"path": "lib/src/main/java/com/foo/Bar.java", "language": "java", "fileCategory": "code"},
        ],
    )
    assert out["importMap"]["src/main/java/com/example/App.java"] == [
        "lib/src/main/java/com/foo/Bar.java",
        "src/main/java/com/foo/Bar.java",
    ]


# ---------------------------------------------------------------------------
# composer.json malformed
# ---------------------------------------------------------------------------


def test_composer_malformed_warning(tmp_path, capsys):
    setup_tree(
        tmp_path,
        {
            "composer.json": '{ "autoload": { "psr-4": { "App\\\\": "src/" }, ',
            "src/Http/Controller.php": "<?php\nnamespace App\\Http;\n\nuse App\\Models\\User;\n\nclass Controller { }\n",
            "src/Models/User.php": "<?php\nnamespace App\\Models;\nclass User { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "composer.json", "language": "json", "fileCategory": "config"},
            {"path": "src/Http/Controller.php", "language": "php", "fileCategory": "code"},
            {"path": "src/Models/User.php", "language": "php", "fileCategory": "code"},
        ],
    )
    stderr = capsys.readouterr().err
    assert "composer.json at" in stderr and "failed to parse" in stderr
    assert "PSR-4 namespace mapping unavailable" in stderr
    assert out["importMap"]["src/Http/Controller.php"] == []


# ---------------------------------------------------------------------------
# tsconfig parse resilience
# ---------------------------------------------------------------------------


def test_tsconfig_malformed_warning(tmp_path, capsys):
    setup_tree(
        tmp_path,
        {
            "tsconfig.json": '{ "compilerOptions": { "baseUrl": ".", ',
            "src/index.ts": "import { foo } from '@/utils';\nimport { bar } from './sibling';\n",
            "src/sibling.ts": "export const bar = 1;\n",
            "src/utils.ts": "export const foo = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/sibling.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/utils.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    stderr = capsys.readouterr().err
    assert "tsconfig.json at" in stderr and "failed to parse" in stderr
    assert "path aliases" in stderr and "will not be applied" in stderr
    assert out["importMap"]["src/index.ts"] == ["src/sibling.ts"]


def test_tsconfig_raw_fallback_slashes(tmp_path, capsys):
    tsconfig_raw = (
        '{\n'
        '  "compilerOptions": {\n'
        '    "baseUrl": ".",\n'
        '    "paths": {\n'
        '      "@scheme//foo/*": ["src/foo/*"]\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    setup_tree(
        tmp_path,
        {
            "tsconfig.json": tsconfig_raw,
            "src/index.ts": "import { x } from '@scheme//foo/bar';\n",
            "src/foo/bar.ts": "export const x = 1;\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "tsconfig.json", "language": "json", "fileCategory": "config"},
            {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
            {"path": "src/foo/bar.ts", "language": "typescript", "fileCategory": "code"},
        ],
    )
    stderr = capsys.readouterr().err
    assert "failed to parse" not in stderr
    assert out["importMap"]["src/index.ts"] == ["src/foo/bar.ts"]


# ---------------------------------------------------------------------------
# Rust crate root missing
# ---------------------------------------------------------------------------


def test_rust_no_crate_root_one_time_warning(tmp_path, capsys):
    setup_tree(
        tmp_path,
        {
            "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\n',
            "app/something.rs": "use crate::auth::login;\nuse crate::db::query;\nfn boot() { }\n",
        },
    )
    out = run(
        tmp_path,
        [
            {"path": "Cargo.toml", "language": "toml", "fileCategory": "config"},
            {"path": "app/something.rs", "language": "rust", "fileCategory": "code"},
        ],
    )
    stderr = capsys.readouterr().err
    crate_warnings = [l for l in stderr.split("\n") if "no crate root" in l]
    assert len(crate_warnings) == 1
    assert "Rust file app/something.rs has 'use crate::' but no crate root" in crate_warnings[0]
    assert out["importMap"]["app/something.rs"] == []
