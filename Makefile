# Understand Anything — root orchestrator.
#
# Two buildable/runnable subprojects, each owning its own config:
#   packages/rust           — Rust analysis engine and skill builders
#   packages/dashboard      — TypeScript (pnpm + Vite) React dashboard
#
# Common targets:
#   make           (default) build all distributable artifacts into dist/
#   make deps      install every subproject's dependencies
#   make install-<platform>... [LOCAL=<dir>] install one or more plugin targets
#   make build     build the Rust engine and dashboard
#   make test      run every subproject's test suite
#   make lint      lint the dashboard
#   make dev       run the dashboard dev server
#   make clean     remove local installed skills, node_modules, build output and caches
# Per-project variants exist too, e.g. `make test-core`, `make build-dashboard`.

PKGS := understand-anything-plugin/packages
RUST := $(PKGS)/rust
DASH := $(PKGS)/dashboard
PLATFORM ?= codex
# LOCAL also selects the repository for local cleanup (defaults to this checkout).
LOCAL ?=
override LOCAL := $(value LOCAL)
export LOCAL PLATFORM
DRY_RUN ?=
export DRY_RUN
# Pass paths via the environment so spaces and shell metacharacters stay literal.
PYTHON ?= python3

# ---- build detection -------------------------------------------------------
# Each expensive step (deps install, dashboard build, dist packaging, deb)
# records a stamp file under $(STAMPDIR). The stamp depends on that step's
# inputs, so Make's timestamp comparison re-runs the step only when an input is
# newer — repeated `make build` / `make install-<platform>`
# are no-ops when nothing changed. `make clean` (and `make clean-stamps`)
# removes the stamps to force a full rebuild.
#
# NOTE: these stamps are intentionally EMPTY files — Make only reads their
# mtimes, never their contents. They live under build/ (which also holds the
# intermediate staging dirs) so all build scratch is in one gitignored place;
# `make clean` wipes build/ and dist/ together.
STAMPDIR := build/.make

# Inputs that invalidate each dependency install.
RUST_SRC := $(shell find $(RUST)/src -type f 2>/dev/null) $(RUST)/Cargo.toml $(RUST)/Cargo.lock
DASH_DEPS_SRC := $(DASH)/package.json $(wildcard $(DASH)/pnpm-lock.yaml)

# Inputs that invalidate the dashboard build (all sources + build config).
DASH_BUILD_SRC := $(shell find $(DASH)/src -type f 2>/dev/null) \
                  $(shell find $(DASH)/public -type f 2>/dev/null) \
                  $(wildcard $(DASH)/*.ts $(DASH)/*.json $(DASH)/*.html)

# Plugin assets exclude generated Rust build artifacts.
PKG_ASSETS := $(shell find understand-anything-plugin \
                -not -path '*/node_modules/*' -not -path '*/target/*' \
                -not -path '*/dist/*' \
                -not -path '*/__pycache__/*' -not -name '*.pyc' -type f 2>/dev/null)
DEB_SRC := $(shell find packaging -type f 2>/dev/null) \
           $(wildcard .claude-plugin/marketplace.json)

# The default goal builds the native plugin and dashboard artifacts into dist/.
.DEFAULT_GOAL := package

# Targets the plugin can be installed for. Per-platform `install-<name>` /
# `uninstall-<name>` targets so `make install-<TAB>` completes the platform.
INSTALL_PLATFORMS := claude codex opencode agents vscode junie jetbrains kilo kiro cursor
INSTALL_TARGETS   := $(addprefix install-,$(INSTALL_PLATFORMS))
UNINSTALL_TARGETS := $(addprefix uninstall-,$(INSTALL_PLATFORMS))

.PHONY: help deps deps-core deps-dashboard \
        $(INSTALL_TARGETS) $(UNINSTALL_TARGETS) \
        build build-core build-dashboard test test-core test-dashboard \
        lint lint-dashboard dev dev-dashboard preview package deb update-dictionaries configure-dictionaries \
        install install-local uninstall-local test-integration engine-help \
        clean clean-local clean-cache clean-build clean-stamps benchmark-large-repo

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '  \033[36m%-18s\033[0m %s\n' "install-<platform>"   "Install one or more targets (make install-kilo install-vscode)"
	@printf '  \033[36m%-18s\033[0m %s\n' "uninstall-<platform>" "Uninstall one or more targets (make uninstall-kilo uninstall-vscode)"
	@printf '  \033[36m%-18s\033[0m %s\n' "  platforms" "$(INSTALL_PLATFORMS)"
	@printf '%s\n' '  Junie: make install-junie [LOCAL=/absolute/path/to/project]' \
		'  JetBrains AI Assistant: make install-jetbrains LOCAL=/absolute/path/to/project'
	@printf '%s\n' '' 'Benchmark example (with a prepared parser cache):' \
		'  make benchmark-large-repo \' \
		'    BENCHMARK_SUBJECT=/absolute/path/to/subject \' \
		'    BENCHMARK_OUTPUT=/tmp/benchmark-results/subject-run-1.benchmark.json \' \
		'    BENCHMARK_PARSER_CACHE=/tmp/ua-benchmark-parsers' \
		'  Keep output outside the subject repository.' \
		'  Parser preparation: docs/benchmarks/large-monorepo.md'

## ---- install the plugin --------------------------------------------------
# Prefers a target's native CLI (e.g. `claude plugin install`, `codex plugin add`)
# and falls back to the scripted symlink installer. See ./install.sh.
#   make install-<platform>... [LOCAL=<project-dir>]  (completes: make install-<TAB>)
#   make install-kilo install-vscode    # installs both; shared build runs once
#   make install-claude                 # native Claude Code install (user scope)
#   LOCAL=. make install-cursor         # project-only target → into the current dir
#   make uninstall-<platform> [LOCAL=<project-dir>]
# Concrete per-platform rules (so `make install-<TAB>` completes the names and the
# recipes actually run — a bare `install-%:` pattern is skipped for .PHONY names).
# install depends on `build` so the dashboard is up to date before the plugin is
# assembled. In `make install-kilo install-vscode`, Make runs that shared build
# prerequisite once, then runs both installers.
define _ua_install_rule
install-$(1): build
	@./install.sh $(1) $$$${LOCAL:+--local "$$$$LOCAL"}
uninstall-$(1):
	@./install.sh --uninstall $(1) $$$${LOCAL:+--local "$$$$LOCAL"}
endef
$(foreach p,$(INSTALL_PLATFORMS),$(eval $(call _ua_install_rule,$(p))))

install: ## Install from source without a dashboard build (PLATFORM=codex, optional LOCAL)
	@./install.sh "$$PLATFORM" $${LOCAL:+--local "$$LOCAL"}

install-local: ## Install standalone skills into LOCAL (default: .; PLATFORM=codex)
	@UA_NO_NATIVE=1 ./install.sh "$$PLATFORM" --local "$${LOCAL:-.}"

uninstall-local: ## Remove this project's local skill links/payload in LOCAL (default: .)
	@$(PYTHON) scripts/clean_local.py --mode skills

## ---- dependencies --------------------------------------------------------
deps: deps-core deps-dashboard ## Install every subproject's deps

deps-core: ## Fetch locked engine dependencies
	cd $(RUST) && cargo +stable fetch --locked
deps-dashboard: $(STAMPDIR)/deps-dashboard ## Install dashboard deps (pnpm)

$(STAMPDIR):
	@mkdir -p $(STAMPDIR)

$(STAMPDIR)/deps-dashboard: $(DASH_DEPS_SRC) | $(STAMPDIR)
	cd $(DASH) && pnpm install
	@touch $@

## ---- build ---------------------------------------------------------------
build: build-core build-dashboard ## Build the Rust engine and dashboard

build-core: ## Build native engine
	cd $(RUST) && cargo +stable build --locked --release

build-dashboard: $(STAMPDIR)/dashboard ## Build the dashboard (tsc + vite)

# Rebuilds only when a source/config file or the dashboard deps are newer.
$(STAMPDIR)/dashboard: $(DASH_BUILD_SRC) $(STAMPDIR)/deps-dashboard | $(STAMPDIR)
	cd $(DASH) && pnpm build
	@touch $@

## ---- test ----------------------------------------------------------------
test: test-core test-dashboard test-integration ## Run all test suites

test-core: ## Run Rust engine tests
	cd $(RUST) && cargo +stable test --locked

test-dashboard: ## Run dashboard tests
	cd $(DASH) && pnpm test

test-integration: ## Run installer and plugin integration regression checks
	$(PYTHON) -m pytest scripts/tests -q

engine-help: ## List deterministic engine commands (builds engine on first use)
	@$(RUST)/run.sh --help

# Opt-in only; independent of test, build, package, and the default goal.
# Paths travel through the environment, preserving spaces and shell metacharacters.
BENCHMARK_SUBJECT ?=
BENCHMARK_OUTPUT ?=
BENCHMARK_PARSER_CACHE ?=
override BENCHMARK_SUBJECT := $(value BENCHMARK_SUBJECT)
override BENCHMARK_OUTPUT := $(value BENCHMARK_OUTPUT)
override BENCHMARK_PARSER_CACHE := $(value BENCHMARK_PARSER_CACHE)
export BENCHMARK_SUBJECT BENCHMARK_OUTPUT BENCHMARK_PARSER_CACHE
benchmark-large-repo: ## Benchmark native stages (BENCHMARK_SUBJECT, BENCHMARK_OUTPUT, BENCHMARK_PARSER_CACHE required)
	@$(PYTHON) scripts/benchmark_large_repo.py "$$BENCHMARK_SUBJECT" --output "$$BENCHMARK_OUTPUT" --parser-cache-dir "$$BENCHMARK_PARSER_CACHE"

## ---- lint ----------------------------------------------------------------
lint: lint-dashboard ## Lint the dashboard

lint-dashboard:
	cd $(DASH) && pnpm lint

## ---- dev / run -----------------------------------------------------------
dev: dev-dashboard ## Run the dashboard dev server
dev-dashboard:
	cd $(DASH) && pnpm dev

preview: ## Preview a production dashboard build
	cd $(DASH) && pnpm preview

## ---- package / distribution ---------------------------------------------
update-dictionaries: ## Detect system dictionaries and refresh only missing local components
	@$(PYTHON) understand-anything-plugin/scripts/configure_dictionaries.py --plugin-root understand-anything-plugin

configure-dictionaries: ## Discover dictionary sources and save paths offline (no downloads)
	@$(PYTHON) understand-anything-plugin/scripts/configure_dictionaries.py --plugin-root understand-anything-plugin --offline

# Bundles omit dictionaries by default and never download them.
package: $(STAMPDIR)/package ## Build native engine, dashboard, and plugin archives into dist/
deb: $(STAMPDIR)/deb ## Build the archives and Debian package into dist/

$(STAMPDIR)/package: $(STAMPDIR)/dashboard $(RUST_SRC) $(PKG_ASSETS) scripts/build_dist.py | $(STAMPDIR)
	python3 scripts/build_dist.py
	@touch $@

$(STAMPDIR)/deb: $(STAMPDIR)/dashboard $(RUST_SRC) $(PKG_ASSETS) $(DEB_SRC) scripts/build_dist.py | $(STAMPDIR)
	python3 scripts/build_dist.py --deb
	@touch $@

## ---- clean ---------------------------------------------------------------
clean: clean-local clean-build ## Clean local installation, caches and build output; preserve indexes

clean-local: ## Remove local skills/payload and caches in LOCAL (default: .); preserve indexes
	@$(PYTHON) scripts/clean_local.py --mode local

clean-cache: ## Clear repo caches/scratch in LOCAL (default: .); preserve indexes and skills
	@$(PYTHON) scripts/clean_local.py --mode cache

clean-build: ## Remove checkout deps/build output/stamps/dist
	@$(PYTHON) scripts/clean_local.py --mode build

clean-stamps: ## Drop only the build-detection stamps (force a rebuild, keep deps/output)
	@$(PYTHON) scripts/clean_local.py --mode stamps
