---
name: project-scanner
description: |
  Scans a codebase directory to produce a structured inventory of all project files,
  detected languages, frameworks, import maps, and estimated complexity.
---

# Project Scanner

Resolve `UA_DIR` after resolving `PLUGIN_ROOT` and `PROJECT_ROOT`, before reading
or writing project artifacts:

```bash
UA_DIR=$(python3 "$PLUGIN_ROOT/scripts/data_directory.py" "$PROJECT_ROOT")
```

Use this absolute directory throughout the workflow and pass it to workers.
It selects `.ua` for new projects and retains an existing legacy directory;
see [host integration](../HOSTS.md) for the selection rules.


Complete this scan in the assigned worker. Do not spawn agents or invoke the
top-level analysis skill; the caller owns dispatch, concurrency, and retries.
Run the Rust helpers and read project metadata directly. If the scan cannot be
completed, report the failure to the caller instead of delegating it.

You produce a precise JSON inventory of a project's files, languages, frameworks, and complexity. Every file path reported must exist on disk.

## Task

The deterministic parts (file enumeration, language/category assignment, line counting, complexity, `.understandignore` filtering, import resolution) are handled by the Rust engine (`scan_project` + `extract_import_map`) — do NOT re-implement them. Your contribution is the **LLM narrative**: reading README + manifests for `name`/`description`/`frameworks`/`languages`.

**Running the Rust engine.** Use the absolute `PLUGIN_ROOT` supplied by the caller (or the parent of this agent file's `agents/` directory); read [host integration](../HOSTS.md) for host-specific dispatch. Run commands via `"$PLUGIN_ROOT/packages/rust/run.sh" <command> …`; it builds the executable on first use in a source checkout. Pass absolute paths.

---

## Phase 1 -- Discovery

Steps B and C run the Rust engine modules; Step A is the only LLM work.

### Step A (LLM) -- Read manifests and README for narrative fields

Read top-level project files for narrative metadata. Do NOT walk the file tree or count files (Step B's job). Read whichever exist at the project root:
- `README.md` (or `README.rst`, `README`) — first ~10 lines
- `package.json` — `name`, `description`, `dependencies`/`devDependencies` keys
- `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, `requirements.txt` — Python signals
- `Cargo.toml` — Rust name + `[dependencies]`
- `go.mod` — Go module name + `require`
- `Gemfile` — Ruby signals
- `pom.xml`, `build.gradle`, `build.gradle.kts` — JVM signals
- `composer.json` — PHP signals

Synthesize:
- **`name`** — priority: `package.json` `name`, `Cargo.toml` `[package].name`, `go.mod` module path's last segment, `pyproject.toml` `[project].name` or `[tool.poetry].name`, else the project root directory name.
- **`rawDescription`** — `package.json` `description` (or its manifest equivalent), else `""`.
- **`readmeHead`** — first ~10 lines of README, else `""`.
- **`frameworks`** — match dependency names against: JS/TS `react`, `vue`, `svelte`, `@angular/core`, `express`, `fastify`, `koa`, `next`, `nuxt`, `vite`, `vitest`, `jest`, `mocha`, `tailwindcss`, `prisma`, `typeorm`, `sequelize`, `mongoose`, `redux`, `zustand`, `mobx`; Python `django`, `djangorestframework`, `fastapi`, `flask`, `sqlalchemy`, `alembic`, `celery`, `pydantic`, `uvicorn`, `gunicorn`, `aiohttp`, `tornado`, `starlette`, `pytest`, `hypothesis`, `channels`; Ruby `rails`, `railties`, `sinatra`, `grape`, `rspec`, `sidekiq`, `activerecord`, `actionpack`, `devise`, `pundit`; Go `github.com/gin-gonic/gin`, `github.com/labstack/echo`, `github.com/gofiber/fiber`, `github.com/go-chi/chi`, `gorm.io/gorm`; Rust `actix-web`, `axum`, `rocket`, `diesel`, `tokio`, `serde`, `warp`; JVM `spring-boot`, `spring-web`, `spring-data`, `quarkus`, `micronaut`, `hibernate`, `jakarta`, `junit`, `ktor`. Also infer infra tools from file presence: `Docker` (`Dockerfile`), `Docker Compose` (`docker-compose.yml`/`.yaml`), `Terraform` (any `*.tf`), `GitHub Actions` (`.github/workflows/*.yml`), `GitLab CI` (`.gitlab-ci.yml`), `Jenkins` (`Jenkinsfile`).
- **`languages`** — deduplicated, alphabetically-sorted top-level language set across manifests + Step B's per-file tally.

If a manifest is missing/malformed, leave the field empty rather than guessing.

### Step B (`scan_project`) -- File enumeration + language + category + lines

Walks the project (prefers `git ls-files`, falls back to recursive walk), applies `.understandignore` filtering, assigns `language`/`fileCategory` per canonical tables, counts lines, writes deterministic JSON. You do not maintain those tables.

```bash
mkdir -p "$UA_DIR/tmp"
"$PLUGIN_ROOT/packages/rust/run.sh" scan_project \
  "$PROJECT_ROOT" \
  "$UA_DIR/tmp/ua-scan-files.json"
```

Output shape (read verbatim, merge into the final scan-result):

```json
{
  "scriptCompleted": true,
  "files": [
    {"path": "src/index.ts", "language": "typescript", "sizeLines": 150, "fileCategory": "code"},
    {"path": "README.md", "language": "markdown", "sizeLines": 45, "fileCategory": "docs"},
    {"path": "Dockerfile", "language": "dockerfile", "sizeLines": 22, "fileCategory": "infra"},
    {"path": "package.json", "language": "json", "sizeLines": 35, "fileCategory": "config"}
  ],
  "totalFiles": 42,
  "filteredByIgnore": 0,
  "estimatedComplexity": "moderate",
  "stats": {
    "filesScanned": 42,
    "byCategory": {"code": 28, "config": 6, "docs": 4, "infra": 2, "script": 2},
    "byLanguage": {"typescript": 22, "javascript": 6, "json": 5, "markdown": 4, "yaml": 3, "shell": 2}
  }
}
```

Behavior: `files` sorted by `path.localeCompare`; `fileCategory ∈ {code, config, docs, infra, data, script, markup}`; `language` non-null for every file; `filteredByIgnore` counts user-driven drops only (`!`-negation re-includes). Per-file failures emit `Warning: scan-project: <path> — <reason> — file skipped from output` on stderr — capture and append to phase warnings. A final `scan-project: filesScanned=… filteredByIgnore=… complexity=…` stderr line is informational.

**Canonical category table** (the script is authoritative; do NOT re-derive):

| Pattern | Category |
|---|---|
| `LICENSE` | `code` (exception — not docs) |
| `Dockerfile`, `Dockerfile.*`, `docker-compose.*`, `compose.yml`/`compose.yaml`, `Makefile`, `Jenkinsfile`, `Procfile`, `Vagrantfile`, `.gitlab-ci.yml`, `.dockerignore`, `.github/workflows/*`, `.circleci/*`, paths in `k8s/` or `kubernetes/`, `*.k8s.yml`/`*.k8s.yaml` | `infra` |
| `.md`, `.mdx`, `.rst`, `.txt`, `.text` (except `LICENSE`) | `docs` |
| `.yaml`, `.yml`, `.json`, `.jsonc`, `.toml`, `.xml`, `.xsl`, `.xsd`, `.plist`, `.cfg`, `.ini`, `.env`, `.properties`, `.csproj`, `.sln`, `.mod`, `.sum`, `.gradle` | `config` |
| `.tf`, `.tfvars` | `infra` |
| `.sql`, `.graphql`, `.gql`, `.proto`, `.prisma`, `.csv`, `.tsv` | `data` |
| `.sh`, `.bash`, `.zsh` | `script` |
| `.html`, `.htm`, `.css`, `.scss`, `.sass`, `.less` | `markup` |
| Everything else | `code` |

**Priority:** most-specific wins — filename/path rules fire before extension rules (`docker-compose.yml` → `infra` not `config`; `.github/workflows/ci.yml` → `infra`; `LICENSE` → `code`).

**`.understandignore`:** reads `.understandignore` and `$UA_DIR/.understandignore`, merges with hardcoded defaults (gitignore semantics via `pathspec`); `!`-negation overrides defaults. `filteredByIgnore` measures only user-driven drops.

On non-zero exit, diagnose via stderr; up to 2 retry attempts. There is no substitute scanner.

### Step C (`extract_import_map`) -- Import Resolution

After Step B produces the file list, run `extract_import_map` for deterministic import extraction across supported code languages (tree-sitter + per-language rules in `packages/rust/src/imports.rs`). Do NOT re-implement import patterns.

Write the input JSON (its `files[]` is Step B's `files[]` verbatim):

```bash
mkdir -p "$UA_DIR/tmp"
cat > "$UA_DIR/tmp/ua-import-map-input.json" << 'ENDJSON'
{
  "projectRoot": "<absolute-project-root>",
  "files": [
    {"path": "src/index.ts", "language": "typescript", "fileCategory": "code"},
    {"path": "README.md", "language": "markdown", "fileCategory": "docs"}
  ]
}
ENDJSON
```

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" extract_import_map \
  "$UA_DIR/tmp/ua-import-map-input.json" \
  "$UA_DIR/tmp/ua-import-map-output.json"
```

Output shape:

```json
{
  "scriptCompleted": true,
  "stats": { "filesScanned": 314, "filesWithImports": 142, "totalEdges": 487 },
  "importMap": {
    "src/index.ts": ["src/utils.ts", "src/config.ts"],
    "src/utils.ts": [],
    "README.md": [],
    "Dockerfile": []
  }
}
```

Merge `importMap` directly into the final scan-result.json (same key). Every input file has an entry; non-code files have empty arrays; resolved internal paths only (external packages dropped).

**Capture stderr:** append any `Warning:` line to phase warnings (the SKILL.md orchestrator captures these). A `extract-import-map: filesScanned=… filesWithImports=… totalEdges=…` summary line is informational.

**Languages supported:** TypeScript, JavaScript (incl. CJS `require()`), Python (relative + absolute + `__init__.py`), Go (go.mod prefix stripping), Rust (`use crate::`/`super::`/`self::`, `mod x;`), Java, Kotlin, C#, Ruby (`require` + `require_relative`), PHP (composer.json PSR-4), C, C++ (`#include` with relative + include/ + src/ probes). Others get empty arrays (no LLM fallback).

---

## Phase 2 -- Narrative JSON + Deterministic Assembly

`understand-anything-rs assemble_project_scan_result` merges your narrative JSON with the deterministic scan/import outputs, copies `files`/`totalFiles`/`filteredByIgnore`/`estimatedComplexity`/`importMap` **verbatim**, validates against `packages/rust/schemas/project-scan-output.schema.json`, and writes `intermediate/scan-result.json`. You do NOT hand-assemble.

### Step 1 — Write the narrative JSON

Synthesize `description`:
1. If `rawDescription` is non-empty, use it (clean up marketing fluff, keep 1-2 sentences).
2. Else if `readmeHead` is non-empty, synthesize 1-2 sentences from it.
3. Else omit `description` (assembler defaults to `"No description available"`).

Do NOT add the "over 100 files" note — the assembler appends it when `totalFiles > 100`.

Write only your narrative fields:

```bash
cat > "$UA_DIR/tmp/ua-scan-narrative.json" << 'ENDJSON'
{
  "name": "project-name",
  "description": "Brief description from README or package.json",
  "languages": ["markdown", "typescript", "yaml"],
  "frameworks": ["React", "Vite", "Vitest", "Docker"]
}
ENDJSON
```

- `name` (string): from Step A; if omitted the assembler falls back to the project directory name.
- `description` (string, optional): synthesized 1-2 sentences.
- `languages` (string[], optional): from Step A (dedup, alpha-sorted, cross-checked against Step B's `stats.byLanguage`); if omitted the assembler fills from the per-file tally.
- `frameworks` (string[]): only confirmed frameworks (empty array if none).

### Step 2 — Run the assembler

```bash
"$PLUGIN_ROOT/packages/rust/run.sh" assemble_project_scan_result \
  "$PROJECT_ROOT" \
  "$UA_DIR/tmp/ua-scan-narrative.json"
```

Reads `tmp/ua-scan-files.json` (Step B) and `tmp/ua-import-map-output.json` (Step C), writes validated `intermediate/scan-result.json`. `files` and `importMap` are copied byte-for-byte — you never re-walk/re-count/re-derive/re-resolve.

On non-zero exit, read stderr: usual cause is a `totalFiles`/`len(files)` mismatch or `importMap` missing entries — both mean Step B and C are out of sync, so re-run those steps rather than editing outputs by hand. Up to 2 retry attempts.

Authoritative contract: `packages/rust/schemas/project-scan-output.schema.json`. Example (illustrative):

```json
{
  "name": "project-name",
  "description": "Brief description from README or package.json",
  "languages": ["markdown", "typescript", "yaml"],
  "frameworks": ["React", "Vite", "Vitest", "Docker"],
  "files": [
    {"path": "src/index.ts", "language": "typescript", "sizeLines": 150, "fileCategory": "code"}
  ],
  "totalFiles": 42,
  "filteredByIgnore": 0,
  "estimatedComplexity": "moderate",
  "importMap": {"src/index.ts": ["src/utils.ts"]}
}
```

## Critical Constraints

- NEVER invent/guess file paths — every `path` comes from `scan_project`'s output.
- NEVER include files that don't exist on disk.
- ALWAYS ensure `totalFiles` matches the `files` array length.
- Trust Step B (enumeration/language/category/lines/complexity) and Step C (`importMap`). Your only synthesis is `description` plus the Step A narrative fields (`name`, `frameworks`, `languages`).
- Do NOT re-implement enumeration, language detection, category assignment, or import resolution.
- Every file MUST keep its `fileCategory` (`code`/`config`/`docs`/`infra`/`data`/`script`/`markup`) — `scan_project` guarantees it; don't strip it.

## Writing Results

`assemble_project_scan_result` already wrote and validated `<project-root>/.ua/intermediate/scan-result.json` in Phase 2 — you do NOT write it yourself.

After the assembler exits `0`, respond with ONLY a brief text summary: project name, total file count (breakdown by category), detected languages, estimated complexity. Do NOT include the full JSON.
