from pathlib import Path

from runtime.safe_commit_review import (
    build_safe_commit_review,
    render_safe_commit_markdown,
    write_safe_commit_review,
)


def _baseline() -> dict[str, object]:
    return {
        "repo_root": "/repo",
        "generated_at": "2026-07-03T09:30:00",
        "summary": {},
        "groups": {
            "source_code": [
                {"status": "M", "path": "runtime/scheduler.py"},
                {"status": "??", "path": "data/tushare_concept_incremental.py"},
            ],
            "governance_docs": [{"status": "??", "path": "docs/dev.md"}],
            "deleted_legacy": [{"status": "D", "path": "scripts/old.py"}],
            "tracked_runtime_artifact": [
                {"status": "M", "path": "reports/dashboard.html"}
            ],
            "runtime_data": [
                {"status": "??", "path": "runs/20260703/"},
                {"status": "??", "path": "data/local.duckdb"},
            ],
            "ignored_generated": [{"status": "!!", "path": "runtime_backups/"}],
            "manual_review": [],
        },
    }


def test_safe_commit_review_separates_stage_exclude_and_hold_groups() -> None:
    review = build_safe_commit_review(_baseline())

    assert review["ready_for_selective_commit"] is True
    assert review["stage_candidates"] == [
        "data/tushare_concept_incremental.py",
        "docs/dev.md",
        "runtime/scheduler.py",
        "scripts/old.py",
    ]
    assert review["git_add_candidates"] == [
        "data/tushare_concept_incremental.py",
        "docs/dev.md",
        "runtime/scheduler.py",
    ]
    assert review["git_update_candidates"] == ["scripts/old.py"]
    assert review["hold_for_review"] == ["reports/dashboard.html"]
    assert review["excluded_runtime"] == [
        "data/local.duckdb",
        "runs/20260703/",
        "runtime_backups/",
    ]


def test_safe_commit_markdown_excludes_runtime_paths_from_git_add() -> None:
    markdown = render_safe_commit_markdown(build_safe_commit_review(_baseline()))

    assert "git add --" in markdown
    git_add_line = next(line for line in markdown.splitlines() if line.startswith("git add --"))
    git_update_line = next(line for line in markdown.splitlines() if line.startswith("git rm --cached"))
    assert "runtime/scheduler.py" in git_add_line
    assert "docs/dev.md" in git_add_line
    assert "scripts/old.py" not in git_add_line
    assert "scripts/old.py" in git_update_line
    assert "reports/dashboard.html" not in git_add_line
    assert "runs/20260703/" not in git_add_line
    assert "runtime_backups/" not in git_add_line
    assert "data/local.duckdb" not in git_add_line


def test_safe_commit_review_writer_creates_compact_json(tmp_path: Path) -> None:
    review = build_safe_commit_review(_baseline())

    paths = write_safe_commit_review(review, tmp_path)

    assert paths["markdown"].exists()
    assert paths["json"].exists()
    assert paths["json"].read_text(encoding="utf-8").count("\n") == 1
