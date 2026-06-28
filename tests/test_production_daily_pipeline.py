"""Production Candidate Daily Pipeline 测试。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.quality_overlay_paper import QualityPaperSnapshot
from pipeline.production_daily import (
    build_monthly_review,
    is_month_end_trade_date,
    validate_pipeline_ready,
    write_daily_artifacts,
    write_run_log,
)


@dataclass
class FakeResult:
    daily_values: pd.Series
    trades: list[dict[str, object]]
    failed_orders: list[dict[str, object]]
    total_cost: float
    turnover_notional: float


@dataclass
class FakeRun:
    result: FakeResult
    exposure: pd.Series


def _fake_run() -> FakeRun:
    dates = pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24"])
    return FakeRun(
        result=FakeResult(
            daily_values=pd.Series([100.0, 101.0, 103.0], index=dates),
            trades=[{"symbol": "AAA.SZ", "quantity": 100, "reason": "monthly_rebalance"}],
            failed_orders=[],
            total_cost=12.0,
            turnover_notional=1000.0,
        ),
        exposure=pd.Series([1.0, 1.0, 1.0], index=dates),
    )


def _snapshot() -> QualityPaperSnapshot:
    return QualityPaperSnapshot(
        trade_date="20260624",
        selection_date="20260529",
        exposure=1.0,
        volatility20=0.2,
        risk_state="NORMAL",
        target_weights={"AAA.SZ": 0.5, "BBB.SZ": 0.5},
        warnings=[],
    )


def test_write_daily_artifacts_outputs_required_files(tmp_path: Path) -> None:
    """每日流水线必须固定输出四个可审计产物。"""
    holdings = pd.DataFrame({"symbol": ["AAA.SZ", "BBB.SZ"], "name": ["甲", "乙"], "target_weight": [0.5, 0.5]})
    previous = QualityPaperSnapshot("20260623", "20260529", 1.0, 0.2, "NORMAL", {"AAA.SZ": 1.0}, [])
    benchmark = pd.Series([1.0, 1.01, 1.02], index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24"]))

    run_dir = write_daily_artifacts(
        output_root=tmp_path,
        snapshot=_snapshot(),
        holdings=holdings,
        run=_fake_run(),
        benchmark_curve=benchmark,
        previous_snapshot=previous,
    )

    assert run_dir == tmp_path / "20260624"
    assert (run_dir / "daily_report.md").exists()
    assert (run_dir / "rebalance_plan.csv").exists()
    assert (run_dir / "portfolio_snapshot.csv").exists()
    metrics = json.loads((run_dir / "strategy_metrics.json").read_text(encoding="utf-8"))
    rebalance = pd.read_csv(run_dir / "rebalance_plan.csv")

    assert metrics["trade_date"] == "20260624"
    assert metrics["risk_state"] == "NORMAL"
    assert metrics["target_exposure"] == 1.0
    assert set(rebalance["action"]) == {"SELL_DOWN", "BUY_NEW"}
    assert "调仓建议" in (run_dir / "daily_report.md").read_text(encoding="utf-8")


def test_validate_pipeline_ready_blocks_stale_benchmark() -> None:
    """基准没有更新到策略日期时不能生成日报。"""
    benchmark = pd.Series([1.0], index=pd.to_datetime(["2026-06-23"]))

    with pytest.raises(RuntimeError, match="基准未更新"):
        validate_pipeline_ready("20260624", benchmark)


def test_write_run_log_records_failure(tmp_path: Path) -> None:
    """任何异常都要写入 run_log，便于长期无人值守排查。"""
    path = write_run_log(tmp_path / "20260624", "FAILED", "数据更新失败")

    assert path.name == "run_log.txt"
    assert "FAILED" in path.read_text(encoding="utf-8")
    assert "数据更新失败" in path.read_text(encoding="utf-8")


def test_build_monthly_review_summarizes_month(tmp_path: Path) -> None:
    """月度汇总应输出本月收益、超额、回撤和风险触发次数。"""
    rows = pd.DataFrame(
        [
            {"trade_date": "20260603", "nav": 1.0, "benchmark_nav": 1.0, "drawdown": 0.0, "exposure": 1.0},
            {"trade_date": "20260624", "nav": 1.1, "benchmark_nav": 1.05, "drawdown": -0.02, "exposure": 0.3},
        ]
    )

    path = build_monthly_review(tmp_path, "202606", rows)

    text = path.read_text(encoding="utf-8")
    assert path.name == "monthly_review.md"
    assert "本月收益" in text
    assert "风险层触发次数" in text


def test_month_end_uses_trading_calendar_not_latest_loaded_data() -> None:
    """月报只能在真实月末交易日生成，不能因为数据只到当日就提前生成。"""
    assert not is_month_end_trade_date("20260624")
    assert is_month_end_trade_date("20260630")
