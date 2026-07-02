"""Deterministic assembly of the final project-scanner contract.

The project-scanner agent contributes only a small *narrative* JSON
(``name`` / ``description`` / ``frameworks`` / optional ``languages``). Every
deterministic field — the file inventory, totals, complexity, and the resolved
import map — is copied verbatim from the outputs of
:mod:`arch_analysis.scan_project` and :mod:`arch_analysis.extract_import_map`.
This module merges those sources, applies the mechanical description rules
(the >100-file note), validates the result against
``project-scan-output.schema.json``, and writes
``intermediate/scan-result.json``.

Usage:
    python -m arch_analysis.assemble_project_scan_result <project-root> <narrative.json>
        [--scan PATH] [--import-map PATH] [--output PATH]

Defaults (relative to ``<project-root>/.understand-anything``):
    --scan         tmp/ua-scan-files.json          (scan_project output)
    --import-map   tmp/ua-import-map-output.json    (extract_import_map output)
    --output       intermediate/scan-result.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .schema import SchemaValidationError, validate_project_scan_output

_LARGE_PROJECT_NOTE = (
    " Note: this project has over 100 source files; consider scoping analysis "
    "to a subdirectory for faster results."
)


class AssemblyError(ValueError):
    """Raised when the deterministic sources are inconsistent or unreadable."""


def assemble_scan_result(
    scan: dict[str, Any],
    import_map_output: dict[str, Any],
    narrative: dict[str, Any],
    project_root: Path | str,
) -> dict[str, Any]:
    """Merge deterministic scan/import outputs with the LLM narrative.

    The ``files`` array, ``totalFiles``, ``filteredByIgnore``,
    ``estimatedComplexity`` and ``importMap`` are copied verbatim from the
    deterministic sources — never re-derived from the narrative. Raises
    :class:`AssemblyError` if the deterministic sources are internally
    inconsistent (e.g. ``totalFiles`` disagrees with ``len(files)``).
    """
    files = scan.get("files")
    if not isinstance(files, list):
        raise AssemblyError("scan output missing 'files' array")

    total_files = scan.get("totalFiles")
    if not isinstance(total_files, int):
        raise AssemblyError("scan output missing integer 'totalFiles'")
    if total_files != len(files):
        raise AssemblyError(
            f"scan output totalFiles ({total_files}) != len(files) ({len(files)})"
        )

    filtered = scan.get("filteredByIgnore")
    if not isinstance(filtered, int):
        raise AssemblyError("scan output missing integer 'filteredByIgnore'")

    complexity = scan.get("estimatedComplexity")
    if not isinstance(complexity, str) or not complexity:
        raise AssemblyError("scan output missing 'estimatedComplexity'")

    import_map = import_map_output.get("importMap")
    if not isinstance(import_map, dict):
        raise AssemblyError("import-map output missing 'importMap' object")

    # Every scanned file must have an importMap entry (non-code files map to []).
    scanned_paths = {f.get("path") for f in files if isinstance(f, dict)}
    missing_entries = [p for p in scanned_paths if p not in import_map]
    if missing_entries:
        preview = ", ".join(sorted(str(p) for p in missing_entries)[:5])
        raise AssemblyError(
            f"importMap is missing entries for {len(missing_entries)} scanned "
            f"file(s) (e.g. {preview}) — scan and import-map outputs are out of sync"
        )

    name = (narrative.get("name") or "").strip()
    if not name:
        name = Path(project_root).resolve().name or "unnamed-project"

    description = (narrative.get("description") or "").strip()
    if not description:
        description = "No description available"
    if total_files > 100 and _LARGE_PROJECT_NOTE.strip() not in description:
        description = description + _LARGE_PROJECT_NOTE

    languages = narrative.get("languages")
    if not isinstance(languages, list) or not languages:
        # Fall back to the deterministic per-file language tally.
        by_language = (scan.get("stats") or {}).get("byLanguage") or {}
        languages = sorted(by_language.keys())

    frameworks = narrative.get("frameworks")
    if not isinstance(frameworks, list):
        frameworks = []

    return {
        "name": name,
        "description": description,
        "languages": list(languages),
        "frameworks": list(frameworks),
        "files": files,
        "totalFiles": total_files,
        "filteredByIgnore": filtered,
        "estimatedComplexity": complexity,
        "importMap": import_map,
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise AssemblyError(f"cannot read {label} ({path}): {err}") from err


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        sys.stderr.write(
            "Usage: python -m arch_analysis.assemble_project_scan_result "
            "<project-root> <narrative.json> "
            "[--scan PATH] [--import-map PATH] [--output PATH]\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    narrative_path = Path(args[1])

    ua = project_root / ".understand-anything"
    scan_path = ua / "tmp" / "ua-scan-files.json"
    import_map_path = ua / "tmp" / "ua-import-map-output.json"
    output_path = ua / "intermediate" / "scan-result.json"

    rest = args[2:]
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--scan" and i + 1 < len(rest):
            scan_path = Path(rest[i + 1]); i += 2; continue
        if arg == "--import-map" and i + 1 < len(rest):
            import_map_path = Path(rest[i + 1]); i += 2; continue
        if arg == "--output" and i + 1 < len(rest):
            output_path = Path(rest[i + 1]); i += 2; continue
        sys.stderr.write(f"assemble_project_scan_result: unknown argument '{arg}'\n")
        return 1

    try:
        scan = _read_json(scan_path, "scan output")
        import_map_output = _read_json(import_map_path, "import-map output")
        narrative = _read_json(narrative_path, "narrative")
        result = assemble_scan_result(scan, import_map_output, narrative, project_root)
        validate_project_scan_output(result)
    except (AssemblyError, SchemaValidationError) as err:
        sys.stderr.write(f"assemble_project_scan_result failed: {err}\n")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    sys.stderr.write(
        f"assemble_project_scan_result: wrote {result['totalFiles']} files, "
        f"{len(result['importMap'])} importMap entries to {output_path}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
