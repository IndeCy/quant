from pathlib import Path

from runtime.operations_observation import (
    build_operations_observation,
    write_operations_observation,
)


def test_operations_observation_reads_latest_run_and_notification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "runs" / "20260703"
    run_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv"]:
        (run_dir / name).write_text("ok", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "scheduler.log").write_text("ok", encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "scheduler.heartbeat").write_text("ok", encoding="utf-8")
    monkeypatch.setenv("BARK_PUSH_URL", "https://example.test/token")

    report = build_operations_observation(tmp_path)

    assert report["latest_run_date"] == "20260703"
    assert report["notification"]["configured"] is True
    assert report["summary"]["fail"] == 0
    assert report["run_artifacts"]["daily_report.md"] == "PASS"
    assert report["scheduler"]["heartbeat"] == "PASS"


def test_operations_observation_warns_when_latest_run_missing_artifacts(tmp_path: Path) -> None:
    (tmp_path / "runs" / "20260703").mkdir(parents=True)

    report = build_operations_observation(tmp_path)

    assert report["latest_run_date"] == "20260703"
    assert report["summary"]["warn"] >= 1
    assert report["run_artifacts"]["daily_report.md"] == "WARN"


def test_operations_observation_uses_latest_complete_daily_run_for_artifacts(tmp_path: Path) -> None:
    complete_dir = tmp_path / "runs" / "20260702"
    complete_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv", "run_log.txt"]:
        (complete_dir / name).write_text("ok", encoding="utf-8")
    pre_market_dir = tmp_path / "runs" / "20260703"
    pre_market_dir.mkdir()
    (pre_market_dir / "pre_market_check.md").write_text("pre market", encoding="utf-8")

    report = build_operations_observation(tmp_path)

    assert report["latest_activity_date"] == "20260703"
    assert report["latest_activity_type"] == "pre_market_only"
    assert report["latest_run_date"] == "20260702"
    assert report["run_artifacts"]["daily_report.md"] == "PASS"


def test_operations_observation_writer_creates_markdown_and_compact_json(tmp_path: Path) -> None:
    report = build_operations_observation(tmp_path)

    paths = write_operations_observation(report, tmp_path)

    assert paths["markdown"].exists()
    assert paths["json"].exists()
    assert paths["json"].read_text(encoding="utf-8").count("\n") == 1
    assert "Operations Observation Summary" in paths["markdown"].read_text(encoding="utf-8")
