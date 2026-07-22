"""开盘前风险复核测试。"""

from pathlib import Path

import pandas as pd
import pytest

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.pre_market_check import run_pre_market_check
from runtime.paths import RuntimePaths
from runtime.risk_policy import RiskPolicyRepository


def test_pre_market_check_no_action_without_previous_risk_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """没有昨日风险单时，不发送 Bark。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    notifications: list[str] = []
    monkeypatch.setattr("runtime.pre_market_check.send_bark_notification", lambda title, body: notifications.append(body))

    result = run_pre_market_check(paths, trade_date="20260703", previous_trade_date="20260702", push=True)

    assert result.status == "NO_ACTION"
    assert result.item_count == 0
    assert notifications == []
    assert (paths.runs_dir / "20260703" / "pre_market_check.md").exists()


def test_pre_market_check_notifies_when_previous_risk_action_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """昨日风险单应在次日开盘前转成执行复核清单。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_strategy_metrics(paths, "20260702", daily_return=-0.1074, drawdown=-0.22, volatility_20=0.68)
    notifications: list[dict[str, str]] = []

    def capture(title: str, body: str):
        notifications.append({"title": title, "body": body})

    monkeypatch.setattr("runtime.pre_market_check.send_bark_notification", capture)

    result = run_pre_market_check(paths, trade_date="20260703", previous_trade_date="20260702", push=True)
    checklist = pd.read_csv(paths.runs_dir / "20260703" / "execution_checklist.csv")

    assert result.status == "NEED_CONFIRM"
    assert result.item_count == 1
    assert checklist.iloc[0]["check_status"] == "PENDING_MANUAL_CONFIRM"
    assert checklist.iloc[0]["recommended_target_exposure"] == pytest.approx(0.30)
    assert notifications[0]["title"] == "开盘前风险复核"
    assert "昨日风险单：1 条" in notifications[0]["body"]
    assert "主线链动因子 V1" in notifications[0]["body"]


def test_pre_market_check_uses_previous_trading_day_on_monday(tmp_path: Path) -> None:
    """周一盘前必须读取周五监控事实，不能把周日当作上一风险日。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_strategy_metrics(paths, "20260717", daily_return=-0.09, drawdown=-0.21, volatility_20=0.55)

    result = run_pre_market_check(paths, trade_date="20260720", push=False)

    assert result.previous_trade_date == "20260717"
    assert result.status == "NEED_CONFIRM"
    assert result.item_count == 1


def test_pre_market_check_marks_active_cap_as_controlled_without_notification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """持续风险上限生效后不应每天重复要求人工确认。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_strategy_metrics(paths, "20260721", daily_return=0.08, drawdown=-0.21, volatility_20=0.55)
    RiskPolicyRepository(paths.system_state_path).activate("mainline_chain_factor_v1", "20260720", 0.3)
    notifications: list[str] = []
    monkeypatch.setattr("runtime.pre_market_check.send_bark_notification", lambda title, body: notifications.append(body))

    result = run_pre_market_check(paths, trade_date="20260722", previous_trade_date="20260721", push=True)
    checklist = pd.read_csv(paths.runs_dir / "20260722" / "execution_checklist.csv")
    report = (paths.runs_dir / "20260722" / "pre_market_check.md").read_text(encoding="utf-8")

    assert result.status == "RISK_CONTROLLED"
    assert checklist.iloc[0]["check_status"] == "RISK_CONTROLLED"
    assert checklist.iloc[0]["active_risk_cap"] == pytest.approx(0.3)
    assert notifications == []
    assert "当前有效风险上限：30.00%" in report


def _seed_strategy_metrics(
    paths: RuntimePaths,
    trade_date: str,
    daily_return: float,
    drawdown: float,
    volatility_20: float,
) -> None:
    paths.ensure_directories()
    end = pd.Timestamp(trade_date)
    dates = pd.DatetimeIndex([end - pd.Timedelta(days=1), end])
    frame = build_strategy_monitor_frame(
        strategy_id="mainline_chain_factor_v1",
        strategy_name="主线链动因子 V1",
        daily_values=pd.Series([100.0, 100.0 * (1 + daily_return)], index=dates),
        benchmark_values=pd.Series([1.0, 1.0], index=dates),
        exposure=pd.Series([1.0, 0.95], index=dates),
    )
    frame.loc[frame.index[-1], "daily_return"] = daily_return
    frame.loc[frame.index[-1], "drawdown"] = drawdown
    frame.loc[frame.index[-1], "volatility_20"] = volatility_20
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(frame)
