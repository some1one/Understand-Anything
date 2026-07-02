"""Port of packages/core/src/__tests__/change-classifier.test.ts."""

from __future__ import annotations

from understand_core.change_classifier import classify_update


def make_analysis(**overrides):
    base = {
        "fileChanges": [],
        "newFiles": [],
        "deletedFiles": [],
        "structurallyChangedFiles": [],
        "cosmeticOnlyFiles": [],
        "unchangedFiles": [],
    }
    base.update(overrides)
    return base


def test_skip_when_all_unchanged():
    decision = classify_update(make_analysis(unchangedFiles=["src/a.ts", "src/b.ts"]), 50)
    assert decision["action"] == "SKIP"
    assert len(decision["filesToReanalyze"]) == 0
    assert decision["rerunArchitecture"] is False


def test_skip_when_all_cosmetic():
    decision = classify_update(make_analysis(cosmeticOnlyFiles=["src/a.ts", "src/b.ts"]), 50)
    assert decision["action"] == "SKIP"
    assert "cosmetic-only" in decision["reason"]


def test_partial_update_for_few_structural():
    analysis = make_analysis(
        structurallyChangedFiles=["src/a.ts", "src/b.ts"],
        newFiles=["src/c.ts"],
        cosmeticOnlyFiles=["src/d.ts"],
    )
    all_known = ["src/a.ts", "src/b.ts", "src/d.ts", "lib/util.ts"]
    decision = classify_update(analysis, 50, all_known)
    assert decision["action"] == "PARTIAL_UPDATE"
    assert decision["filesToReanalyze"] == ["src/a.ts", "src/b.ts", "src/c.ts"]
    assert decision["rerunArchitecture"] is False


def test_architecture_update_when_over_10_structural():
    files = [f"src/file{i}.ts" for i in range(12)]
    decision = classify_update(make_analysis(structurallyChangedFiles=files), 50)
    assert decision["action"] == "ARCHITECTURE_UPDATE"
    assert decision["rerunArchitecture"] is True


def test_architecture_update_when_new_directories():
    analysis = make_analysis(structurallyChangedFiles=["src/existing.ts"], newFiles=["newdir/file.ts"])
    all_known = ["src/existing.ts", "src/other.ts", "lib/util.ts"]
    decision = classify_update(analysis, 50, all_known)
    assert decision["action"] == "ARCHITECTURE_UPDATE"
    assert decision["rerunArchitecture"] is True


def test_architecture_update_when_directories_deleted():
    analysis = make_analysis(structurallyChangedFiles=["src/existing.ts"], deletedFiles=["olddir/removed.ts"])
    all_known = ["src/existing.ts", "src/other.ts"]
    decision = classify_update(analysis, 50, all_known)
    assert decision["action"] == "ARCHITECTURE_UPDATE"
    assert decision["rerunArchitecture"] is True


def test_no_architecture_update_for_new_file_in_existing_dir():
    analysis = make_analysis(newFiles=["src/newfile.ts"])
    all_known = ["src/a.ts", "src/b.ts", "lib/util.ts"]
    decision = classify_update(analysis, 50, all_known)
    assert decision["action"] == "PARTIAL_UPDATE"
    assert decision["rerunArchitecture"] is False


def test_architecture_update_for_new_file_in_new_dir():
    analysis = make_analysis(newFiles=["brand-new-pkg/index.ts"])
    all_known = ["src/a.ts", "src/b.ts", "lib/util.ts"]
    decision = classify_update(analysis, 50, all_known)
    assert decision["action"] == "ARCHITECTURE_UPDATE"
    assert decision["rerunArchitecture"] is True


def test_full_update_when_over_30_structural():
    files = [f"src/file{i}.ts" for i in range(35)]
    decision = classify_update(make_analysis(structurallyChangedFiles=files), 100)
    assert decision["action"] == "FULL_UPDATE"
    assert decision["rerunArchitecture"] is True


def test_full_update_when_over_half_project():
    files = [f"src/file{i}.ts" for i in range(6)]
    decision = classify_update(make_analysis(structurallyChangedFiles=files), 10)
    assert decision["action"] == "FULL_UPDATE"


def test_files_to_reanalyze_for_partial():
    analysis = make_analysis(
        structurallyChangedFiles=["src/modified.ts"],
        newFiles=["src/added.ts"],
        deletedFiles=["src/removed.ts"],
    )
    decision = classify_update(analysis, 50)
    assert "src/modified.ts" in decision["filesToReanalyze"]
    assert "src/added.ts" in decision["filesToReanalyze"]
    assert "src/removed.ts" not in decision["filesToReanalyze"]


def test_empty_analysis():
    decision = classify_update(make_analysis(), 50)
    assert decision["action"] == "SKIP"
    assert "No changes detected" in decision["reason"]


def test_deleted_files_count_toward_structural():
    analysis = make_analysis(
        structurallyChangedFiles=[f"src/file{i}.ts" for i in range(8)],
        deletedFiles=["src/old1.ts", "src/old2.ts", "src/old3.ts"],
    )
    decision = classify_update(analysis, 50)
    assert decision["action"] == "ARCHITECTURE_UPDATE"
