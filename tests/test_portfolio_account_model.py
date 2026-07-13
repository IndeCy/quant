"""统一账户与组合模型测试。"""

from pathlib import Path

import pytest

from runtime.portfolio_account import build_account_snapshot
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_build_account_snapshot_calculates_drift_and_trade_amounts() -> None:
    """账户快照应同时表达目标、实际、漂移和调仓金额。"""
    snapshot = build_account_snapshot(
        strategy_id="quality_overlay",
        trade_date="20260702",
        total_value=1_000_000.0,
        cash=100_000.0,
        target_weights={"000001.SZ": 0.50, "000002.SZ": 0.30},
        actual_positions={
            "000001.SZ": {"market_value": 400_000.0, "quantity": 10_000, "last_close": 40.0},
            "000003.SZ": {"market_value": 100_000.0, "quantity": 2_000, "last_close": 50.0},
        },
    )

    by_symbol = {item["symbol"]: item for item in snapshot["positions"]}
    assert snapshot["cash_weight"] == pytest.approx(0.10)
    assert by_symbol["000001.SZ"]["actual_weight"] == pytest.approx(0.40)
    assert by_symbol["000001.SZ"]["drift_weight"] == pytest.approx(-0.10)
    assert by_symbol["000001.SZ"]["trade_amount"] == pytest.approx(100_000.0)
    assert by_symbol["000002.SZ"]["action"] == "BUY"
    assert by_symbol["000003.SZ"]["action"] == "SELL"


def test_repository_saves_and_loads_account_snapshot(tmp_path: Path) -> None:
    """系统状态库应保存策略账户快照和持仓明细。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    snapshot = build_account_snapshot(
        strategy_id="quality_overlay",
        trade_date="20260702",
        total_value=1_000_000.0,
        cash=100_000.0,
        target_weights={"000001.SZ": 0.50},
        actual_positions={"000001.SZ": {"market_value": 400_000.0, "quantity": 10_000, "last_close": 40.0}},
    )

    repository.upsert_account_snapshot(snapshot)
    loaded = repository.load_account_snapshot("quality_overlay")

    assert loaded is not None
    assert loaded["strategy_id"] == "quality_overlay"
    assert loaded["trade_date"] == "20260702"
    assert loaded["positions"][0]["symbol"] == "000001.SZ"
    assert loaded["positions"][0]["trade_amount"] == pytest.approx(100_000.0)


def test_local_api_exposes_account_snapshot(tmp_path: Path) -> None:
    """本地 API 应能读取策略账户视图。"""
    from api.service import LocalApiService

    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    service = LocalApiService(paths)
    snapshot = build_account_snapshot(
        strategy_id="quality_overlay",
        trade_date="20260702",
        total_value=1_000_000.0,
        cash=100_000.0,
        target_weights={"000001.SZ": 0.50},
        actual_positions={"000001.SZ": {"market_value": 400_000.0, "quantity": 10_000, "last_close": 40.0}},
    )
    service.system_repository.upsert_account_snapshot(snapshot)

    result = service.account_snapshot("quality_overlay")

    assert result is not None
    assert result["cash_weight"] == pytest.approx(0.10)
