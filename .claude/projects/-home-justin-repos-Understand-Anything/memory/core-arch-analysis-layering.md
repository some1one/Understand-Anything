---
name: core-arch-analysis-layering
description: The single merged understand_core Python package (arch_analysis was folded in, 2026-07-06)
metadata:
  type: project
---

As of 2026-07-06 there is **one** Python package: `understand-anything-plugin/packages/core`. The formerly-separate `arch_analysis` package was folded into `understand_core` (all its flat modules now live directly under `understand_core/`, imported with relative imports like `from .models import …`). `skill_builders/` remains a second top-level package in the same PDM project.

Key points after the merge:
- The deterministic pipeline runs via **`packages/core/run.sh <module> …`** (was `packages/arch_analysis/run.sh`). `run.sh` sets `PYTHONPATH=packages/core` and execs `python -m understand_core.<module>`. Module-name args are unchanged (e.g. `run.sh scan_project …`).
- **Schema collision resolved:** arch's strict JSON-Schema validator is now `understand_core/json_schema.py` (validates against `understand_core/schemas/*.json`); the browser-parity view-model schema keeps the name `understand_core/schema.py`. They are different files — don't conflate. `persistence.py` imports the view-model `.schema` (`validate_graph`); the pipeline modules import `.json_schema`.
- One `pyproject.toml`, one `.venv`, one `pdm.lock`, one wheel (`understand-anything-core`), one test suite (`make test-core`; `test-arch` is gone). `pytest pythonpath = ["."]`.
- Build simplified: no more flat-package staging in `scripts/build_dist.py` — `understand_core` is a normal package dir, so a plain `pdm build` ships it (schemas/ + structure/ included as package data).

Note: the tracked `.agents/understand-anything-plugin/` tree is a **stale** committed install snapshot (predates several refactors) and was NOT updated in this merge. Related: [[skill-path-roots]].
