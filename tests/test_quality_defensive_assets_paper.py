"""Quality防守袖套Paper可执行性研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.paper_execution import PaperTradingResult, PortfolioSnapshot
from examples import quality_defensive_assets_paper_study as study
from examples import quality_defensive_assets_paper_gap_study as gap_study
from examples import quality_defensive_assets_paper_actual_study as actual_study
from examples.quality_defensive_assets_paper_actual_metrics import (
    actual_position_gap_frame,
    evaluate_actual_account_gate,
)
from examples.quality_defensive_assets_paper_metrics import (
    evaluate_incremental_paper_gate,
    evaluate_paper_gate,
)
from examples.strategy_comparison_research import BacktestResearchResult


def test_paper_market_data_converts_tushare_lots_to_shares() -> None:
    """成交量必须从Tushare手数转换为Broker使用的股数。"""
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-02"), "AAA")],
        names=["date", "symbol"],
    )
    bars = pd.DataFrame(
        {
            "open": [10.0],
            "close": [10.0],
            "volume": [123.0],
            "is_suspended": [False],
            "limit_up": [False],
            "limit_down": [False],
        },
        index=index,
    )

    frame = study.build_paper_market_data(bars)

    assert frame.iloc[0]["volume"] == 12_300.0


def test_paper_gate_rejects_excess_tracking_error() -> None:
    """收益指标合格也不能掩盖Paper跟踪误差超限。"""
    m0 = _metrics(0.12, -0.18, 0.80)
    paper = {
        "paper_baseline": _metrics(0.11, -0.19, 0.75),
        "paper_stress": _metrics(0.10, -0.22, 0.65),
    }
    diagnostics = {
        "paper_baseline": _diagnostics(0.04),
        "paper_stress": _diagnostics(0.07),
    }

    passed = evaluate_paper_gate(m0, paper, diagnostics)
    diagnostics["paper_baseline"]["tracking_error"] = 0.06
    failed = evaluate_paper_gate(m0, paper, diagnostics)

    assert passed["passed"] is True
    assert failed["passed"] is False
    assert failed["checks"]["baseline_tracking_error_below_5pct"] is False


def test_paper_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同执行口径和数据版本不得重复历史撮合。"""

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study.STRATEGY_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复撮合"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def test_incremental_gate_uses_paper_failures_above_m0_only() -> None:
    """M0共同拦截不能被重复记为Paper新增拒单。"""
    m0 = _metrics(0.12, -0.18, 0.80)
    paper = {
        "paper_baseline": _metrics(0.11, -0.19, 0.75),
        "paper_stress": _metrics(0.10, -0.22, 0.65),
    }
    diagnostics = {
        "paper_baseline": _incremental_diagnostics(0.01),
        "paper_stress": _incremental_diagnostics(0.04),
    }

    passed = evaluate_incremental_paper_gate(m0, paper, diagnostics)
    diagnostics["paper_baseline"]["incremental_rejection_rate_vs_m0"] = 0.03
    failed = evaluate_incremental_paper_gate(m0, paper, diagnostics)

    assert passed["passed"] is True
    assert failed["passed"] is False
    assert (
        failed["checks"]["baseline_incremental_rejections_below_2pct"]
        is False
    )


def test_paper_gap_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V2相同比较口径不得重复历史撮合。"""

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": gap_study.STRATEGY_ID}

    monkeypatch.setattr(
        gap_study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        gap_study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复撮合"),
    )

    result = gap_study.run_study(gap_study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def test_actual_position_gap_compares_paper_with_m0_fills() -> None:
    """停牌导致的共同目标漂移不应误算成Paper相对M0偏差。"""
    paper_result = PaperTradingResult(
        orders=[],
        executions=[],
        snapshots=[
            PortfolioSnapshot(
                date="2024-01-03",
                cash=100.0,
                total_value=1_000.0,
                actual_holdings={"AAA": 90},
                target_holdings={"AAA": 100},
                drift={"AAA": -10},
                unrealized_pnl={},
            )
        ],
        actual_turnover=0.0,
    )
    m0_result = BacktestResearchResult(
        strategy="m0",
        daily_values=pd.Series(
            [1_000.0],
            index=[pd.Timestamp("2024-01-03")],
        ),
        trades=[
            {
                "date": pd.Timestamp("2024-01-03"),
                "symbol": "AAA",
                "quantity": 100,
                "price": 10.0,
                "fee": 0.0,
            }
        ],
        failed_orders=[],
        total_cost=0.0,
        turnover_notional=1_000.0,
    )
    market = pd.DataFrame(
        [{"date": "2024-01-03", "symbol": "AAA", "close": 10.0}]
    )

    frame = actual_position_gap_frame(paper_result, market, m0_result)

    assert frame.iloc[0]["position_gap"] == pytest.approx(0.10)


def test_actual_account_gate_uses_actual_position_gap() -> None:
    """V3必须用实际账户差异，而不是理想目标漂移。"""
    m0 = _metrics(0.12, -0.18, 0.80)
    paper = {
        "paper_baseline": _metrics(0.11, -0.19, 0.75),
        "paper_stress": _metrics(0.10, -0.22, 0.65),
    }
    diagnostics = {
        "paper_baseline": {
            **_incremental_diagnostics(0.01),
            "average_actual_position_gap": 0.04,
            "latest_actual_position_gap": 0.03,
        },
        "paper_stress": {
            **_incremental_diagnostics(0.04),
            "average_actual_position_gap": 0.09,
            "latest_actual_position_gap": 0.08,
        },
    }

    passed = evaluate_actual_account_gate(m0, paper, diagnostics)
    diagnostics["paper_baseline"]["average_actual_position_gap"] = 0.06
    failed = evaluate_actual_account_gate(m0, paper, diagnostics)

    assert passed["passed"] is True
    assert failed["passed"] is False


def test_actual_account_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V3相同实际账户比较不得重复撮合。"""

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": actual_study.STRATEGY_ID}

    monkeypatch.setattr(
        actual_study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        actual_study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复撮合"),
    )

    result = actual_study.run_study(
        actual_study.RuntimePaths(tmp_path),
        "20260724",
    )

    assert result["reused"] is True


def _metrics(
    annual_return: float,
    drawdown: float,
    sharpe: float,
) -> dict[str, float]:
    return {
        "annualized_return": annual_return,
        "max_drawdown": drawdown,
        "sharpe": sharpe,
        "calmar": 0.60,
        "excess_return": 0.20,
        "annual_turnover": 5.0,
        "trade_count": 100.0,
        "execution_cost_impact": 0.02,
    }


def _diagnostics(tracking_error: float) -> dict[str, float]:
    return {
        "fill_rate": 0.99,
        "rejection_rate": 0.01,
        "partial_order_rate": 0.10,
        "average_position_drift": 0.03,
        "max_position_drift": 0.08,
        "tracking_error": tracking_error,
        "total_return_gap": -0.05,
        "execution_cost_to_initial_cash": 0.20,
        "order_count": 100.0,
    }


def _incremental_diagnostics(
    incremental_rejection_rate: float,
) -> dict[str, float]:
    """构造相对M0偏差门槛使用的最小指标。"""
    return {
        **_diagnostics(0.04),
        "successful_order_ratio_vs_m0": 0.99,
        "incremental_rejection_rate_vs_m0": incremental_rejection_rate,
        "average_post_execution_drift": 0.04,
        "max_post_execution_drift": 0.08,
        "latest_position_drift": 0.03,
    }
