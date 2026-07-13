from pathlib import Path

from runtime.post_baseline_audit import (
    build_post_baseline_audit,
    write_post_baseline_audit,
)


def test_post_baseline_audit_passes_with_required_scripts(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "runs" / "20260703").mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    (tmp_path / "scripts" / "run_daily_pipeline.py").write_text("", encoding="utf-8")
    (tmp_path / "reports" / "dashboard.html").write_text("<html></html>", encoding="utf-8")

    report = build_post_baseline_audit(
        tmp_path,
        required_scripts=["scripts/run_daily_pipeline.py"],
    )

    assert report["summary"]["fail"] == 0
    assert report["summary"]["pass"] >= 2
    assert any(item["name"] == "required_scripts" for item in report["checks"])
    assert any(item["name"] == "runtime_outputs_present" for item in report["checks"])


def test_post_baseline_audit_fails_when_required_script_missing(tmp_path: Path) -> None:
    report = build_post_baseline_audit(
        tmp_path,
        required_scripts=["scripts/run_daily_pipeline.py"],
    )

    missing = next(item for item in report["checks"] if item["name"] == "required_scripts")
    assert missing["status"] == "FAIL"
    assert "scripts/run_daily_pipeline.py" in missing["details"]


def test_git_runtime_boundary_ignores_untracked_runtime_outputs(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "runs" / "20260703").mkdir(parents=True)
    (tmp_path / "runs" / "20260703" / "daily_report.md").write_text("runtime", encoding="utf-8")

    report = build_post_baseline_audit(tmp_path, required_scripts=[])
    boundary = next(item for item in report["checks"] if item["name"] == "git_runtime_boundary")

    assert boundary["status"] == "PASS"


def test_post_baseline_audit_writer_creates_markdown_and_compact_json(tmp_path: Path) -> None:
    report = build_post_baseline_audit(tmp_path, required_scripts=[])

    paths = write_post_baseline_audit(report, tmp_path)

    assert paths["markdown"].exists()
    assert paths["json"].exists()
    assert paths["json"].read_text(encoding="utf-8").count("\n") == 1
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Post-Baseline Operations Audit" in markdown
