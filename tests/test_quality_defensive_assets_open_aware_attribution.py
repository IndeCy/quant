"""Open-aware Paper 失败归因研究测试。"""

from __future__ import annotations

import pandas as pd

from backtest.paper_execution import (
    PaperOrder,
    PaperTradingResult,
    PortfolioSnapshot,
)
from examples import quality_defensive_assets_open_aware_attribution_study as study
from examples.quality_defensive_assets_open_aware_attribution_metrics import (
    build_order_alignment,
    summarize_order_alignment,
)
from examples.strategy_comparison_research import BacktestResearchResult


def test_alignment_classifies_disappearing_order_as_t1_zero_delta() -> None:
    """开盘重算后无需交易的旧订单不能被记为真实漏单。"""
    legacy = _paper(
        [_order(1, "AAA", "BUY", 100)],
    )
    open_aware = _paper([])
    market = pd.DataFrame(
        [
            {
                "date": "2024-01-03",
                "symbol": "AAA",
                "open": 10.0,
            }
        ]
    )

    alignment = build_order_alignment(
        legacy,
        open_aware,
        {"20240102": {"AAA": 1.0}},
        market,
    )

    assert alignment.iloc[0]["category"] == "LEGACY_ONLY_T1_DELTA_ZERO"
    assert bool(alignment.iloc[0]["batch_missing_open"]) is False


def test_alignment_detects_missing_open_batch() -> None:
    """目标股票缺少开盘价时必须明确归因到整批跳过。"""
    legacy = _paper(
        [_order(1, "AAA", "BUY", 100)],
    )
    open_aware = _paper([])
    market = pd.DataFrame(
        [
            {
                "date": "2024-01-03",
                "symbol": "AAA",
                "open": 0.0,
            }
        ]
    )

    alignment = build_order_alignment(
        legacy,
        open_aware,
        {"20240102": {"AAA": 1.0}},
        market,
    )

    assert (
        alignment.iloc[0]["category"]
        == "LEGACY_ONLY_MISSING_OPEN_BATCH"
    )
    assert bool(alignment.iloc[0]["batch_missing_open"]) is True


def test_diagnosis_treats_zero_delta_gap_as_metric_mismatch() -> None:
    """少单由零差额解释且拒单未增加时，不应误判执行缺陷。"""
    order_summary = {
        "generated_order_gap_vs_legacy": -10,
        "missing_open_batch_count": 0,
        "rejected_order_change": -2,
        "category_breakdown": {
            "LEGACY_ONLY_T1_DELTA_ZERO": {"order_count": 10}
        },
    }
    tracking = {"tracking_error_annualized": 0.021}

    diagnosis = study.diagnose_gate_failure(order_summary, tracking)

    assert diagnosis["execution_defect_found"] is False
    assert diagnosis["count_metric_mismatch_supported"] is True
    assert diagnosis["tracking_error_still_above_v5_gate"] is True


def test_order_summary_preserves_m0_success_count() -> None:
    """归因必须保留M0基数，不能只比较两种Paper。"""
    legacy = _paper([_order(1, "AAA", "BUY", 100)])
    open_aware = _paper([_order(1, "AAA", "BUY", 100)])
    alignment = pd.DataFrame(
        [
            {
                "category": "MATCHED_SAME_SIDE",
                "symbol": "AAA",
                "legacy_notional": 1_000.0,
                "open_aware_notional": 1_000.0,
                "batch_missing_open": False,
                "signal_date": "2024-01-02",
            }
        ]
    )
    m0 = BacktestResearchResult(
        strategy="m0",
        daily_values=pd.Series(
            [1.0],
            index=[pd.Timestamp("2024-01-03")],
        ),
        trades=[{"date": "2024-01-03"}, {"date": "2024-01-03"}],
        failed_orders=[],
        total_cost=0.0,
        turnover_notional=0.0,
    )

    summary = summarize_order_alignment(
        alignment,
        legacy,
        open_aware,
        m0,
    )

    assert summary["m0_successful_orders"] == 2
    assert summary["open_aware_successful_orders"] == 1


def _order(
    order_id: int,
    symbol: str,
    side: str,
    quantity: int,
) -> PaperOrder:
    return PaperOrder(
        order_id=order_id,
        signal_date="2024-01-02",
        execute_date="2024-01-03",
        symbol=symbol,
        side=side,
        quantity=quantity,
        signal_price=10.0,
        status="FILLED",
        filled_quantity=quantity,
        fill_price=10.0,
    )


def _paper(orders: list[PaperOrder]) -> PaperTradingResult:
    return PaperTradingResult(
        orders=orders,
        executions=[],
        snapshots=[
            PortfolioSnapshot(
                date="2024-01-03",
                cash=0.0,
                total_value=1_000.0,
                actual_holdings={},
                target_holdings={},
                drift={},
                unrealized_pnl={},
            )
        ],
        actual_turnover=0.0,
    )
