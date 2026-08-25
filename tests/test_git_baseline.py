from pathlib import Path

from runtime.git_baseline import (
    classify_git_path,
    parse_status_lines,
    summarize_entries,
    write_git_baseline_report,
)


def test_classify_git_paths_separates_commit_safe_and_runtime_files() -> None:
    assert classify_git_path("runtime/scheduler.py", " M") == "source_code"
    assert classify_git_path("frontend/src/App.tsx", " M") == "source_code"
    assert classify_git_path(".planning/STATE.md", "??") == "governance_docs"
    assert classify_git_path(".gitignore", " M") == "governance_docs"
    assert classify_git_path("docs/development_workflow.md", "??") == "governance_docs"
    assert classify_git_path("frontend/src/entities/account/", "??") == "source_code"
    assert classify_git_path("runtime_backups/quant.tar.gz", "!!") == "ignored_generated"
    assert classify_git_path("data/local.duckdb", "??") == "runtime_data"
    assert classify_git_path("runs/20260703/daily_report.md", "??") == "runtime_data"
    assert classify_git_path("reports/dashboard_data.json", " M") == "tracked_runtime_artifact"
    assert classify_git_path("monitoring/mainline_adapter.py", " D") == "deleted_legacy"


def test_parse_status_lines_preserves_status_and_path() -> None:
    entries = parse_status_lines([" M runtime/scheduler.py", "?? .planning/STATE.md"])

    assert entries[0].status == "M"
    assert entries[0].path == "runtime/scheduler.py"
    assert entries[0].classification == "source_code"
    assert entries[1].status == "??"
    assert entries[1].path == ".planning/STATE.md"
    assert entries[1].classification == "governance_docs"


def test_summarize_entries_groups_by_classification() -> None:
    entries = parse_status_lines([" M runtime/scheduler.py", "?? data/cache.duckdb"])

    grouped = summarize_entries(entries)

    assert [item.path for item in grouped["source_code"]] == ["runtime/scheduler.py"]
    assert [item.path for item in grouped["runtime_data"]] == ["data/cache.duckdb"]


def test_write_git_baseline_report_creates_json_and_markdown(tmp_path: Path) -> None:
    entries = parse_status_lines([" M runtime/scheduler.py", "?? data/cache.duckdb"])
    report = {
        "repo_root": "/repo",
        "summary": {"source_code": 1, "runtime_data": 1},
        "groups": {
            key: [entry.to_dict() for entry in value]
            for key, value in summarize_entries(entries).items()
        },
    }

    paths = write_git_baseline_report(report, tmp_path)

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert paths["json"].read_text(encoding="utf-8").count("\n") == 1
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Git Baseline Report" in markdown
    assert "runtime/scheduler.py" in markdown
    assert "data/cache.duckdb" in markdown
