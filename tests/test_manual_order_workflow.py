"""人工调仓单工作流测试。"""

from pathlib import Path

from runtime.manual_order import build_order_draft_from_snapshot
from runtime.portfolio_account import build_account_snapshot
from runtime.repository import SystemRepository


def _snapshot() -> dict:
    """构造包含买入、卖出和保留差异的账户快照。"""
    return build_account_snapshot(
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


def test_build_order_draft_from_account_snapshot_filters_hold_rows() -> None:
    """账户快照应生成只包含实际调仓金额的手工订单草案。"""
    draft = build_order_draft_from_snapshot(_snapshot(), min_trade_amount=1_000.0)

    assert draft["strategy_id"] == "quality_overlay"
    assert draft["trade_date"] == "20260702"
    assert draft["status"] == "DRAFT"
    assert [item["symbol"] for item in draft["orders"]] == ["000001.SZ", "000002.SZ", "000003.SZ"]
    assert draft["orders"][0]["side"] == "BUY"
    assert draft["orders"][2]["side"] == "SELL"


def test_repository_persists_manual_order_batch_and_audit_log(tmp_path: Path) -> None:
    """系统状态库应持久化手工调仓批次、订单和审计事件。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    created = repository.create_manual_order_batch(_snapshot())
    loaded = repository.load_manual_order_batch("quality_overlay", "20260702")

    assert loaded is not None
    assert loaded["batch_id"] == created["batch_id"]
    assert loaded["status"] == "DRAFT"
    assert len(loaded["orders"]) == 3
    assert loaded["audit_events"][0]["event_type"] == "CREATE"
