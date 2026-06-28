"""冻结Quality Overlay策略的Paper状态测试。"""

import importlib
from pathlib import Path

import pytest

from backtest.quality_overlay_paper import QualityPaperSnapshot, QualityPaperStore, build_target_weights
from examples import run_quality_overlay_paper
from runtime.repository import SystemRepository


def test_target_weights_respect_overlay_exposure() -> None:
    weights = build_target_weights(["A", "B", "C"], exposure=0.3)

    assert weights == pytest.approx({"A": 0.1, "B": 0.1, "C": 0.1})
    assert abs(sum(weights.values()) - 0.3) < 1e-12


def test_snapshot_store_is_idempotent_by_trade_date(tmp_path: Path) -> None:
    store = QualityPaperStore(tmp_path / "paper.sqlite3")
    first = QualityPaperSnapshot("20260618", "20260529", 1.0, 0.30, "NORMAL", {"A": 1.0}, [])
    revised = QualityPaperSnapshot("20260618", "20260529", 0.3, 0.50, "REDUCED", {"A": 0.3}, ["test"])

    store.save(first)
    store.save(revised)
    loaded = store.load("20260618")

    assert store.count() == 1
    assert loaded is not None
    assert loaded.exposure == 0.3
    assert loaded.target_weights == {"A": 0.3}
    assert loaded.warnings == ["test"]


def test_snapshot_store_loads_latest_before_trade_date(tmp_path: Path) -> None:
    """调仓计划需要拿到目标日前最近一次快照做权重差异。"""
    store = QualityPaperStore(tmp_path / "paper.sqlite3")
    first = QualityPaperSnapshot("20260618", "20260529", 1.0, 0.20, "NORMAL", {"A": 1.0}, [])
    second = QualityPaperSnapshot("20260620", "20260529", 0.3, 0.50, "REDUCED", {"A": 0.3}, [])
    store.save(first)
    store.save(second)

    loaded = store.load_latest_before("20260620")

    assert loaded is not None
    assert loaded.trade_date == "20260618"
    assert loaded.target_weights == {"A": 1.0}


def test_push_report_uses_notification_message(monkeypatch) -> None:
    sent = []

    class FakeNotifier:
        def send(self, message) -> None:
            sent.append(message)

    monkeypatch.setattr(run_quality_overlay_paper, "build_notifier", lambda provider, endpoint: FakeNotifier())
    snapshot = QualityPaperSnapshot("20260618", "20260529", 1.0, 0.2, "NORMAL", {"A": 1.0}, [])

    run_quality_overlay_paper.push_report(snapshot, "https://example.test/key")

    assert sent[0].title == "Quality Overlay Paper"
    assert "目标仓位100%" in sent[0].body


def test_daily_script_mutable_paths_follow_quant_home(monkeypatch, tmp_path: Path) -> None:
    """设置 QUANT_HOME 后，每日运行产物必须集中写入运行目录。"""
    runtime_home = tmp_path / "quant_runtime"
    monkeypatch.setenv("QUANT_HOME", str(runtime_home))

    reloaded = importlib.reload(run_quality_overlay_paper)

    assert reloaded.INCREMENT_PATH == runtime_home / "data" / "live_market_increment.duckdb"
    assert reloaded.BENCHMARK_INCREMENT_PATH == runtime_home / "data" / "benchmark_increment.duckdb"
    assert reloaded.PAPER_PATH == runtime_home / "data" / "quality_overlay_paper.sqlite3"
    assert reloaded.MONITORING_PATH == runtime_home / "data" / "monitoring.sqlite3"
    assert reloaded.REPORT_PATH == runtime_home / "reports" / "quality_overlay_paper_latest.md"
    assert reloaded.DASHBOARD_HTML_PATH == runtime_home / "reports" / "dashboard.html"
    assert reloaded.RUNS_ROOT == runtime_home / "runs"

    monkeypatch.delenv("QUANT_HOME", raising=False)
    importlib.reload(run_quality_overlay_paper)


def test_register_daily_artifacts_indexes_required_outputs(tmp_path: Path) -> None:
    """日报、调仓建议、组合快照和指标 JSON 都要进入报告索引。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    run_dir = tmp_path / "runs" / "20260624"

    run_quality_overlay_paper.register_daily_artifacts(repository, "20260624", run_dir)

    reports = repository.list_reports("quality_overlay")
    report_types = {item["report_type"] for item in reports}
    assert report_types == {"daily_report", "rebalance_plan", "portfolio_snapshot", "strategy_metrics"}
    assert {Path(item["file_path"]).parent for item in reports} == {run_dir}
