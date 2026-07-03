"""开盘前风险复核测试。"""

from pathlib import Path

import pandas as pd
import pytest

from runtime.pre_market_check import run_pre_market_check
from runtime.paths import RuntimePaths


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
    risk_dir = paths.runs_dir / "20260702"
    risk_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "trade_date": "20260702",
                "strategy_id": "mainline_chain_factor_v1",
                "strategy_name": "主线链动因子 V1",
                "severity": "CRITICAL",
                "action_status": "NEED_CONFIRM",
                "suggested_action": "T+1开盘前复核，人工确认是否风险减仓",
                "reasons": "当日收益 -10.74% <= -8%",
            }
        ]
    ).to_csv(risk_dir / "risk_actions.csv", index=False)
    notifications: list[dict[str, str]] = []

    def capture(title: str, body: str):
        notifications.append({"title": title, "body": body})

    monkeypatch.setattr("runtime.pre_market_check.send_bark_notification", capture)

    result = run_pre_market_check(paths, trade_date="20260703", previous_trade_date="20260702", push=True)
    checklist = pd.read_csv(paths.runs_dir / "20260703" / "execution_checklist.csv")

    assert result.status == "NEED_CONFIRM"
    assert result.item_count == 1
    assert checklist.iloc[0]["check_status"] == "PENDING_MANUAL_CONFIRM"
    assert notifications[0]["title"] == "开盘前风险复核"
    assert "昨日风险单：1 条" in notifications[0]["body"]
    assert "主线链动因子 V1" in notifications[0]["body"]
