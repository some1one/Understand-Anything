"""Deterministic per-batch input/context preparation for the file-analyzer.

Replaces the file-analyzer's manual construction of the ``extract_structure``
input JSON and prose-maintained cross-batch neighbor map. Reads the
``batches.json`` produced by :mod:`arch_analysis.compute_batches` and, for each
requested ``batchIndex``, writes two files into the project's ``tmp`` dir:

  - ``ua-file-analyzer-input-<batchIndex>.json`` — the ``extract_structure``
    input (``projectRoot`` + ``batchFiles`` + ``batchImportData``).
  - ``ua-file-context-<batchIndex>.json`` — the deterministic
    :class:`~arch_analysis.models.FileAnalysisContext` consumed by the seeding
    and finalization steps (adds the cross-batch ``neighborMap``).

Usage:
    python -m arch_analysis.prepare_file_analysis_batch <project-root> <batchIndex> [<batchIndex>...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .schema import (
    SchemaValidationError,
    validate_file_analysis_context,
    validate_structure_input,
)


class PrepareError(ValueError):
    """Raised when batches.json is missing, malformed, or lacks a batch index."""


def _batch_files(batch: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in batch.get("files", []):
        if not isinstance(f, dict):
            continue
        out.append(
            {
                "path": f.get("path"),
                "language": f.get("language"),
                "sizeLines": f.get("sizeLines"),
                "fileCategory": f.get("fileCategory"),
            }
        )
    return out


def build_batch_payloads(
    project_root: str,
    batch: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(structure_input, file_analysis_context)`` for one batch entry."""
    batch_index = batch.get("batchIndex")
    batch_files = _batch_files(batch)
    batch_import_data = batch.get("batchImportData") or {}
    neighbor_map = batch.get("neighborMap") or {}

    structure_input = {
        "projectRoot": project_root,
        "batchFiles": batch_files,
        "batchImportData": batch_import_data,
    }

    context = {
        "projectRoot": project_root,
        "batchIndex": batch_index,
        "batchFiles": batch_files,
        "batchImportData": batch_import_data,
        "neighborMap": neighbor_map,
    }
    return structure_input, context


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        sys.stderr.write(
            "Usage: python -m arch_analysis.prepare_file_analysis_batch "
            "<project-root> <batchIndex> [<batchIndex>...]\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    try:
        wanted = [int(a) for a in args[1:]]
    except ValueError:
        sys.stderr.write("prepare_file_analysis_batch: batch indices must be integers\n")
        return 1

    ua = project_root / ".understand-anything"
    batches_path = ua / "intermediate" / "batches.json"
    tmp_dir = ua / "tmp"

    try:
        batches_doc = json.loads(batches_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(
            f"prepare_file_analysis_batch failed: cannot read {batches_path}: {err}\n"
        )
        return 1

    by_index: dict[int, dict[str, Any]] = {}
    for b in batches_doc.get("batches", []):
        if isinstance(b, dict) and isinstance(b.get("batchIndex"), int):
            by_index[b["batchIndex"]] = b

    tmp_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for idx in wanted:
        batch = by_index.get(idx)
        if batch is None:
            sys.stderr.write(
                f"prepare_file_analysis_batch failed: batch {idx} not found in "
                f"{batches_path} (available: {sorted(by_index)})\n"
            )
            return 1

        structure_input, context = build_batch_payloads(str(project_root), batch)
        try:
            validate_structure_input(structure_input)
            validate_file_analysis_context(context)
        except SchemaValidationError as err:
            sys.stderr.write(
                f"prepare_file_analysis_batch failed: batch {idx} produced invalid "
                f"payload: {err}\n"
            )
            return 1

        input_path = tmp_dir / f"ua-file-analyzer-input-{idx}.json"
        context_path = tmp_dir / f"ua-file-context-{idx}.json"
        input_path.write_text(
            json.dumps(structure_input, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        context_path.write_text(
            json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written += 1
        sys.stderr.write(
            f"prepare_file_analysis_batch: batch {idx} → "
            f"{len(context['batchFiles'])} files, "
            f"{len(context['neighborMap'])} neighbor entries\n"
        )

    sys.stderr.write(f"prepare_file_analysis_batch: prepared {written} batch(es)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
