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
#   make install <platform> [LOCAL=<dir>]   install the plugin for an agent/IDE
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
        lint lint-dashboard dev dev-dashboard preview package deb package-python clean

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '  \033[36m%-18s\033[0m %s\n' "install-<platform>"   "Install the plugin ([LOCAL=<dir>] make install-<platform>)"
	@printf '  \033[36m%-18s\033[0m %s\n' "uninstall-<platform>" "Uninstall the plugin ([LOCAL=<dir>] make uninstall-<platform>)"
	@printf '  \033[36m%-18s\033[0m %s\n' "  platforms" "$(INSTALL_PLATFORMS)"

## ---- install the plugin --------------------------------------------------
# Prefers a target's native CLI (e.g. `claude plugin install`, `codex plugin add`)
# and falls back to the scripted symlink installer. See ./install.sh.
#   make install-<platform> [LOCAL=<project-dir>]     (completes: make install-<TAB>)
#   make install-claude                 # native Claude Code install (user scope)
#   LOCAL=. make install-cursor         # project-only target → into the current dir
#   make uninstall-<platform> [LOCAL=<project-dir>]
# Concrete per-platform rules (so `make install-<TAB>` completes the names and the
# recipes actually run — a bare `install-%:` pattern is skipped for .PHONY names).
define _ua_install_rule
install-$(1):
	@./install.sh $(1) $$(if $$(LOCAL),--local $$(LOCAL))
uninstall-$(1):
	@./install.sh --uninstall $(1) $$(if $$(LOCAL),--local $$(LOCAL))
endef
$(foreach p,$(INSTALL_PLATFORMS),$(eval $(call _ua_install_rule,$(p))))

## ---- dependencies --------------------------------------------------------
deps: deps-arch deps-core deps-dashboard ## Install every subproject's deps

deps-arch: ## Install arch_analysis deps (Python/PDM)
	cd $(ARCH) && pdm install

deps-core: ## Install core deps (Python/PDM)
	cd $(CORE) && pdm install

deps-dashboard: ## Install dashboard deps (pnpm)
	cd $(DASH) && pnpm install

## ---- build ---------------------------------------------------------------
build: build-dashboard ## Build everything with a build step (the dashboard)

build-dashboard: ## Build the dashboard (tsc + vite)
	cd $(DASH) && pnpm build

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
package: ## Build wheels + wheelhouse + dashboard and the archives into dist/
	python3 scripts/build_dist.py

deb: ## Build the archives AND the Debian package (linux_x64 / py3.14) into dist/
	python3 scripts/build_dist.py --deb

package-python: ## Build only the Python wheels + sdists + wheelhouse into dist/python/
	python3 scripts/build_dist.py --python-only

## ---- clean ---------------------------------------------------------------
clean: ## Remove venvs, node_modules, build output, caches, and dist/
	rm -rf $(ARCH)/.venv $(CORE)/.venv
	rm -rf $(DASH)/node_modules $(DASH)/dist
	rm -rf build dist
	find $(PKGS) -type d -name __pycache__ -prune -exec rm -rf {} +
	find $(PKGS) -type d -name .pytest_cache -prune -exec rm -rf {} +
