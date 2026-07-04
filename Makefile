# Understand Anything — root orchestrator.
#
# Three buildable/runnable subprojects, each owning its own config:
#   packages/arch_analysis  — Python (PDM)   deterministic analysis engine
#   packages/core           — Python (PDM)   ported @understand-anything/core + skill builders
#   packages/dashboard      — TypeScript (pnpm + Vite) React dashboard
#
# Common targets:
#   make           (default) build all distributable artifacts into dist/
#   make deps      install every subproject's dependencies
#   make install-<platform>... [LOCAL=<dir>] install one or more plugin targets
#   make build     build everything that has a build step (the dashboard)
#   make test      run every subproject's test suite
#   make lint      lint the dashboard
#   make dev       run the dashboard dev server
#   make clean     remove venvs, node_modules, build output and caches
# Per-project variants exist too, e.g. `make test-core`, `make build-dashboard`.

PKGS := understand-anything-plugin/packages
ARCH := $(PKGS)/arch_analysis
CORE := $(PKGS)/core
DASH := $(PKGS)/dashboard

# pdm's generated bin/pytest shebang is not portable across a moved/copied venv,
# so always invoke pytest as a module.
PYTEST := pdm run python -m pytest

# ---- build detection -------------------------------------------------------
# Each expensive step (deps install, dashboard build, dist packaging, deb)
# records a stamp file under $(STAMPDIR). The stamp depends on that step's
# inputs, so Make's timestamp comparison re-runs the step only when an input is
# newer — repeated `make build` / `make install-<platform>` / `make package`
# are no-ops when nothing changed. `make clean` (and `make clean-stamps`)
# removes the stamps to force a full rebuild.
#
# NOTE: these stamps are intentionally EMPTY files — Make only reads their
# mtimes, never their contents. They are not build artifacts. Real output goes
# to build/ (intermediate staging) and dist/ (release archives). The dir is
# named .make (not .build) so it isn't mistaken for build output or
# confused with the build/ staging dir.
STAMPDIR := .make

# Inputs that invalidate each dependency install.
ARCH_DEPS_SRC := $(ARCH)/pyproject.toml $(wildcard $(ARCH)/pdm.lock)
CORE_DEPS_SRC := $(CORE)/pyproject.toml $(wildcard $(CORE)/pdm.lock)
DASH_DEPS_SRC := $(DASH)/package.json $(wildcard $(DASH)/pnpm-lock.yaml)

# Inputs that invalidate the dashboard build (all sources + build config).
DASH_BUILD_SRC := $(shell find $(DASH)/src -type f 2>/dev/null) \
                  $(shell find $(DASH)/public -type f 2>/dev/null) \
                  $(wildcard $(DASH)/*.ts $(DASH)/*.json $(DASH)/*.html)

# Python sources that invalidate packaging (tests excluded — not shipped in the
# wheels).
PY_SRC := $(shell find $(ARCH) $(CORE) -name '*.py' \
            -not -path '*/.venv/*' -not -path '*/__pycache__/*' \
            -not -path '*/tests/*' 2>/dev/null)

# The full payload that goes into the release archives / deb: packaged Python
# sources, the dashboard build stamp, the build script, and the plugin's
# non-Python assets (skills, agents, hooks, manifests, run.sh, serve.mjs).
PKG_ASSETS := $(shell find understand-anything-plugin \
                -not -path '*/node_modules/*' -not -path '*/.venv/*' \
                -not -path '*/dist/*' -not -path '*/__pycache__/*' \
                -not -name '*.pyc' -type f 2>/dev/null)
DEB_SRC := $(shell find packaging -type f 2>/dev/null) \
           $(wildcard .claude-plugin/marketplace.json)

# The default goal builds all distributable artifacts (wheels + wheelhouse +
# dashboard + release archives) into dist/. Run `make help` for the full list.
.DEFAULT_GOAL := package

# Targets the plugin can be installed for. Per-platform `install-<name>` /
# `uninstall-<name>` targets so `make install-<TAB>` completes the platform.
INSTALL_PLATFORMS := claude codex opencode agents vscode jetbrains kilo kiro cursor
INSTALL_TARGETS   := $(addprefix install-,$(INSTALL_PLATFORMS))
UNINSTALL_TARGETS := $(addprefix uninstall-,$(INSTALL_PLATFORMS))

.PHONY: help deps deps-arch deps-core deps-dashboard \
        $(INSTALL_TARGETS) $(UNINSTALL_TARGETS) \
        build build-dashboard test test-arch test-core test-dashboard \
        lint lint-dashboard dev dev-dashboard preview package deb package-python \
        clean clean-stamps

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '  \033[36m%-18s\033[0m %s\n' "install-<platform>"   "Install one or more targets (make install-kilo install-vscode)"
	@printf '  \033[36m%-18s\033[0m %s\n' "uninstall-<platform>" "Uninstall one or more targets (make uninstall-kilo uninstall-vscode)"
	@printf '  \033[36m%-18s\033[0m %s\n' "  platforms" "$(INSTALL_PLATFORMS)"

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
	@./install.sh $(1) $$(if $$(LOCAL),--local $$(LOCAL))
uninstall-$(1):
	@./install.sh --uninstall $(1) $$(if $$(LOCAL),--local $$(LOCAL))
endef
$(foreach p,$(INSTALL_PLATFORMS),$(eval $(call _ua_install_rule,$(p))))

## ---- dependencies --------------------------------------------------------
deps: deps-arch deps-core deps-dashboard ## Install every subproject's deps

deps-arch: $(STAMPDIR)/deps-arch ## Install arch_analysis deps (Python/PDM)
deps-core: $(STAMPDIR)/deps-core ## Install core deps (Python/PDM)
deps-dashboard: $(STAMPDIR)/deps-dashboard ## Install dashboard deps (pnpm)

$(STAMPDIR):
	@mkdir -p $(STAMPDIR)

$(STAMPDIR)/deps-arch: $(ARCH_DEPS_SRC) | $(STAMPDIR)
	cd $(ARCH) && pdm install
	@touch $@

$(STAMPDIR)/deps-core: $(CORE_DEPS_SRC) | $(STAMPDIR)
	cd $(CORE) && pdm install
	@touch $@

$(STAMPDIR)/deps-dashboard: $(DASH_DEPS_SRC) | $(STAMPDIR)
	cd $(DASH) && pnpm install
	@touch $@

## ---- build ---------------------------------------------------------------
build: build-dashboard ## Build everything with a build step (the dashboard)

build-dashboard: $(STAMPDIR)/dashboard ## Build the dashboard (tsc + vite)

# Rebuilds only when a source/config file or the dashboard deps are newer.
$(STAMPDIR)/dashboard: $(DASH_BUILD_SRC) $(STAMPDIR)/deps-dashboard | $(STAMPDIR)
	cd $(DASH) && pnpm build
	@touch $@

## ---- test ----------------------------------------------------------------
test: test-arch test-core test-dashboard ## Run all test suites

test-arch: ## Run arch_analysis tests
	cd $(ARCH) && $(PYTEST)

test-core: ## Run core tests
	cd $(CORE) && $(PYTEST)

test-dashboard: ## Run dashboard tests
	cd $(DASH) && pnpm test

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
# Each variant is stamped independently — it re-runs only when the dashboard
# build, a packaged source/asset, the build script, or (for deb) the packaging
# files changed.
package: $(STAMPDIR)/package ## Build wheels + wheelhouse + dashboard and the archives into dist/
deb: $(STAMPDIR)/deb ## Build the archives AND the Debian package (linux_x64 / py3.14) into dist/
package-python: $(STAMPDIR)/package-python ## Build only the Python wheels + sdists + wheelhouse into dist/python/

$(STAMPDIR)/package: $(STAMPDIR)/dashboard $(PY_SRC) $(PKG_ASSETS) scripts/build_dist.py | $(STAMPDIR)
	python3 scripts/build_dist.py
	@touch $@

$(STAMPDIR)/deb: $(STAMPDIR)/dashboard $(PY_SRC) $(PKG_ASSETS) $(DEB_SRC) scripts/build_dist.py | $(STAMPDIR)
	python3 scripts/build_dist.py --deb
	@touch $@

$(STAMPDIR)/package-python: $(PY_SRC) $(ARCH_DEPS_SRC) $(CORE_DEPS_SRC) scripts/build_dist.py | $(STAMPDIR)
	python3 scripts/build_dist.py --python-only
	@touch $@

## ---- clean ---------------------------------------------------------------
clean: ## Remove venvs, node_modules, build output, caches, stamps, and dist/
	rm -rf $(ARCH)/.venv $(CORE)/.venv
	rm -rf $(DASH)/node_modules $(DASH)/dist
	rm -rf build dist $(STAMPDIR)
	find $(PKGS) -type d -name __pycache__ -prune -exec rm -rf {} +
	find $(PKGS) -type d -name .pytest_cache -prune -exec rm -rf {} +

clean-stamps: ## Drop only the build-detection stamps (force a rebuild, keep deps/output)
	rm -rf $(STAMPDIR)
