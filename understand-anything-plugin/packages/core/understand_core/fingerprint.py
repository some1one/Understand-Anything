"""Fingerprint wire shapes — typed views over ``fingerprints.json``.

The structural-fingerprint *logic* (extraction, comparison, store build, and
update classification) lives in :mod:`understand_core.fingerprints`, which the
deterministic pipeline drives via ``build_fingerprints`` / ``auto_update_*``.
This module only carries the camelCase ``TypedDict`` shapes for the on-disk
``fingerprints.json`` store (used as type annotations by
:mod:`understand_core.persistence`) and re-exports
:func:`understand_core.fingerprints.content_hash`.
"""

from __future__ import annotations

from typing import Literal, TypedDict

# The SHA-256 content hash is owned by understand_core (identical hex digest).
from understand_core.fingerprints import content_hash

ChangeLevel = Literal["NONE", "COSMETIC", "STRUCTURAL"]


# ---------------------------------------------------------------------------
# Fingerprint TypedDicts (wire shapes for fingerprints.json)
# ---------------------------------------------------------------------------


class FunctionFingerprint(TypedDict, total=False):
    name: str
    params: list[str]
    returnType: str | None
    exported: bool
    lineCount: int


class ClassFingerprint(TypedDict, total=False):
    name: str
    methods: list[str]
    properties: list[str]
    exported: bool
    lineCount: int


class ImportFingerprint(TypedDict):
    source: str
    specifiers: list[str]


class FileFingerprint(TypedDict, total=False):
    filePath: str
    contentHash: str
    functions: list[FunctionFingerprint]
    classes: list[ClassFingerprint]
    imports: list[ImportFingerprint]
    exports: list[str]
    totalLines: int
    hasStructuralAnalysis: bool


class FingerprintStore(TypedDict, total=False):
    version: str
    gitCommitHash: str
    generatedAt: str
    files: dict[str, FileFingerprint]


__all__ = [
    "ChangeLevel",
    "FunctionFingerprint",
    "ClassFingerprint",
    "ImportFingerprint",
    "FileFingerprint",
    "FingerprintStore",
    "content_hash",
]
