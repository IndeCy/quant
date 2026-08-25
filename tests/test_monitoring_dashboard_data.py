"""Dashboard 数据导出测试。"""

from __future__ import annotations

import json

import pandas as pd

from monitoring.dashboard_data import build_dashboard_payload, write_dashboard_files
from monitoring.repository import MonitoringRepository


def test_dashboard_payload_contains_series_summary_and_market(tmp_path) -> None:
    """前端报表需要同时拿到折线序列、摘要指标和大盘状态。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    repo.upsert_strategy_daily(
        pd.DataFrame(
            [
                {
                    "trade_date": "20240102",
                    "strategy_id": "quality_overlay",
                    "strategy_name": "Quality Overlay",
                    "nav": 1.0,
                    "daily_return": 0.0,
                    "cumulative_return": 0.0,
                    "benchmark_id": "510300",
                    "benchmark_nav": 1.0,
                    "benchmark_return": 0.0,
                    "excess_return": 0.0,
                    "drawdown": 0.0,
                    "max_drawdown": 0.0,
                    "volatility_20": 0.2,
                    "volatility_60": 0.3,
                    "sharpe_rolling": 0.5,
                    "exposure": 1.0,
                    "turnover_notional": 10.0,
                    "total_execution_cost": 1.0,
                    "failed_order_count": 0,
                }
            ]
        )
    )
    repo.upsert_market_daily(
        pd.DataFrame(
            [
                {
                    "trade_date": "20240102",
                    "benchmark_id": "510300",
                    "benchmark_nav": 1.0,
                    "benchmark_return": 0.0,
                    "benchmark_drawdown": 0.0,
                    "ma60": 1.0,
                    "ma120": 0.9,
                    "trend_state": "UP",
                    "breadth_up_count": 10,
                    "breadth_down_count": 5,
                    "limit_up_count": 1,
                    "limit_down_count": 0,
                }
            ]
        )
    )

    payload = build_dashboard_payload(repo, strategy_id="quality_overlay", benchmark_id="510300")
    json_path = tmp_path / "dashboard_data.json"
    html_path = tmp_path / "dashboard.html"
    write_dashboard_files(payload, json_path, html_path)

    assert payload["summary"]["trade_date"] == "20240102"
    assert payload["summary"]["risk_light"] == "GREEN"
    assert payload["summary"]["action_state"] == "不操作"
    assert payload["strategy_series"][0]["nav"] == 1.0
    assert payload["market_summary"]["trend_state"] == "UP"
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["strategy_id"] == "quality_overlay"
    assert "Quality Strategy Monitor" in html_path.read_text(encoding="utf-8")


def test_dashboard_payload_marks_risk_warning_and_deleveraging(tmp_path) -> None:
    """波动率进入阈值区间时给出灯色，仓位下降时直接提示风险降仓。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    repo.upsert_strategy_daily(
        pd.DataFrame(
            [
                _strategy_row("20240102", volatility_20=0.34, exposure=1.0),
                _strategy_row("20240103", volatility_20=0.46, exposure=0.3),
            ]
        )
    )

    payload = build_dashboard_payload(repo, strategy_id="quality_overlay")

    assert payload["summary"]["risk_light"] == "RED"
    assert payload["summary"]["risk_light_label"] == "红色"
    assert payload["summary"]["action_state"] == "风险降仓"
    assert "仓位从100.00%降到30.00%" in payload["summary"]["action_reason"]


def test_dashboard_payload_marks_recovery_and_execution_review(tmp_path) -> None:
    """仓位恢复和新增失败委托都应转成可读操作状态。"""
    repo = MonitoringRepository(tmp_path / "monitoring.sqlite3")
    repo.upsert_strategy_daily(
        pd.DataFrame(
            [
                _strategy_row("20240102", volatility_20=0.50, exposure=0.3, failed_order_count=2),
                _strategy_row("20240103", volatility_20=0.30, exposure=1.0, failed_order_count=2),
            ]
        )
    )
    recovery = build_dashboard_payload(repo, strategy_id="quality_overlay")
    assert recovery["summary"]["action_state"] == "风险恢复"

    repo.upsert_strategy_daily(
        pd.DataFrame([_strategy_row("20240104", volatility_20=0.20, exposure=1.0, failed_order_count=3)])
    )
    failed = build_dashboard_payload(repo, strategy_id="quality_overlay")
    assert failed["summary"]["action_state"] == "执行异常复查"


def _strategy_row(
    trade_date: str,
    volatility_20: float,
    exposure: float,
    failed_order_count: int = 0,
) -> dict[str, object]:
    """构造监控测试行。"""
    return {
        "trade_date": trade_date,
        "strategy_id": "quality_overlay",
        "strategy_name": "Quality Overlay",
        "nav": 1.0,
        "daily_return": 0.0,
        "cumulative_return": 0.0,
        "benchmark_id": "510300",
        "benchmark_nav": 1.0,
        "benchmark_return": 0.0,
        "excess_return": 0.0,
        "drawdown": 0.0,
        "max_drawdown": 0.0,
        "volatility_20": volatility_20,
        "volatility_60": volatility_20,
        "sharpe_rolling": 0.0,
        "exposure": exposure,
        "turnover_notional": 0.0,
        "total_execution_cost": 0.0,
        "failed_order_count": failed_order_count,
    }
