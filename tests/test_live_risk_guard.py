"""盘后实盘风险处置测试。"""

from pathlib import Path

import pandas as pd
import pytest

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.live_risk_guard import run_live_risk_guard
from runtime.paths import RuntimePaths


def test_live_risk_guard_creates_no_action_for_normal_strategy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """风险指标正常时只写报告，不发送 Bark。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_strategy_metrics(paths, daily_return=-0.01, drawdown=-0.03, volatility_20=0.20)
    notifications: list[str] = []
    monkeypatch.setattr("runtime.live_risk_guard.send_bark_notification", lambda title, body: notifications.append(body))

    result = run_live_risk_guard(paths, trade_date="20260702", push=True)

    assert result.status == "NORMAL"
    assert result.action_count == 0
    assert notifications == []
    assert (paths.runs_dir / "20260702" / "risk_guard_report.md").exists()
    assert (paths.runs_dir / "20260702" / "risk_actions.csv").exists()


def test_live_risk_guard_notifies_critical_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """单日大跌、深回撤和高波动应触发人工风险确认。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_strategy_metrics(paths, daily_return=-0.1074, drawdown=-0.2209, volatility_20=0.6846)
    notifications: list[dict[str, str]] = []

    def capture(title: str, body: str):
        notifications.append({"title": title, "body": body})

    monkeypatch.setattr("runtime.live_risk_guard.send_bark_notification", capture)

    result = run_live_risk_guard(paths, trade_date="20260702", push=True)
    actions = pd.read_csv(paths.runs_dir / "20260702" / "risk_actions.csv")
    report = (paths.runs_dir / "20260702" / "risk_guard_report.md").read_text(encoding="utf-8")

    assert result.status == "CRITICAL"
    assert result.action_count == 1
    assert actions.iloc[0]["action_status"] == "NEED_CONFIRM"
    assert actions.iloc[0]["severity"] == "CRITICAL"
    assert actions.iloc[0]["recommended_target_exposure"] == pytest.approx(0.30)
    assert "当日收益 -10.74%" in actions.iloc[0]["reasons"]
    assert "当前回撤 -22.09%" in actions.iloc[0]["reasons"]
    assert notifications[0]["title"] == "量化风险处置触发"
    assert "明日开盘前复核" in notifications[0]["body"]
    assert "主线链动因子 V1" in report


def _seed_strategy_metrics(paths: RuntimePaths, daily_return: float, drawdown: float, volatility_20: float) -> None:
    paths.ensure_directories()
    dates = pd.to_datetime(["2026-07-01", "2026-07-02"])
    # 先用通用计算器建表，再覆盖测试关注的最新指标，避免测试耦合净值构造细节。
    frame = build_strategy_monitor_frame(
        strategy_id="mainline_chain_factor_v1",
        strategy_name="主线链动因子 V1",
        daily_values=pd.Series([100.0, 100.0 * (1 + daily_return)], index=dates),
        benchmark_values=pd.Series([1.0, 1.0], index=dates),
        exposure=pd.Series([1.0, 0.96], index=dates),
    )
    frame.loc[frame.index[-1], "daily_return"] = daily_return
    frame.loc[frame.index[-1], "drawdown"] = drawdown
    frame.loc[frame.index[-1], "volatility_20"] = volatility_20
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(frame)
