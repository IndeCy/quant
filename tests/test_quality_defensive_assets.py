"""Quality防守资产证券级组合研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.mixed_asset_execution import MixedAssetExecutionModel
from examples import quality_defensive_assets_study as study
from examples.quality_defensive_assets_metrics import (
    build_risk_path_diagnostics,
    evaluate_gate,
)
from examples.quality_risk_layer_research import RiskLayerRun
from examples.strategy_comparison_research import BacktestResearchResult
from portfolio.fixed_sleeve import blend_fixed_sleeve_targets


def test_fixed_sleeve_blends_security_weights_to_one() -> None:
    """核心证券缩放后必须与黄金、国债合计100%。"""
    result = blend_fixed_sleeve_targets(
        {"20240131": {"A": 0.5, "B": 0.5}},
        core_allocation=0.70,
        defensive_weights={"GOLD": 0.15, "BOND": 0.15},
    )

    assert result["20240131"] == {
        "A": 0.35,
        "B": 0.35,
        "GOLD": 0.15,
        "BOND": 0.15,
    }
    assert sum(result["20240131"].values()) == pytest.approx(1.0)


def test_mixed_execution_charges_stamp_tax_only_for_stock() -> None:
    """股票和ETF都经过M0，但只有股票卖出收印花税。"""
    model = MixedAssetExecutionModel({"ETF"}, slippage_bps=5.0)
    bar = pd.Series(
        {
            "open": 10.0,
            "close": 10.0,
            "is_suspended": False,
            "limit_up": False,
            "limit_down": False,
        }
    )

    stock = model.simulate_order("STOCK", -1000, bar, pd.Timestamp("2024-01-02"))
    fund = model.simulate_order("ETF", -1000, bar, pd.Timestamp("2024-01-02"))

    assert stock.success and fund.success
    assert stock.stamp_tax > 0
    assert fund.stamp_tax == 0
    assert stock.slippage_cost == pytest.approx(fund.slippage_cost)


def test_gate_requires_material_drawdown_improvement() -> None:
    """绝对指标合格但未改善核心回撤时仍不能通过。"""
    blend = {key: _metrics(-0.20) for key in [*study.FOLDS, "full"]}
    core = {"full": _metrics(-0.22)}
    annual = {str(year): _metrics(-0.10) for year in range(2015, 2027)}
    correlations = {"defensive_core": 0.1}

    gate = evaluate_gate(blend, core, annual, correlations)

    assert gate["passed"] is False
    assert gate["checks"]["drawdown_improves_core_by_3pct"] is False


def test_risk_path_reports_delayed_blend_trigger() -> None:
    """防守资产改变波动路径时，诊断必须展示触发延迟。"""
    dates = pd.bdate_range("2015-05-27", "2015-06-03")
    core = _risk_run(dates, [1.0, 0.3, 0.3, 1.0, 1.0, 1.0])
    blend = _risk_run(dates, [1.0, 1.0, 1.0, 0.3, 0.3, 1.0])

    result = build_risk_path_diagnostics(
        {"core": core, "blend": blend},
        core_id="core",
        blend_id="blend",
    )

    assert result["core"]["first_reduced_date_2015"] == "20150528"
    assert result["blend"]["first_reduced_date_2015"] == "20150601"
    assert result["blend_trigger_delay_trading_days"] == 2


def test_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """固定证券级组合命中研究指纹后不能重扫财务大表。"""

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
        lambda *args, **kwargs: pytest.fail("不应重复回测"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _metrics(drawdown: float) -> dict[str, float]:
    return {
        "annualized_return": 0.12,
        "max_drawdown": drawdown,
        "sharpe": 0.80,
        "calmar": 0.60,
        "excess_return": 0.20,
        "annual_turnover": 5.0,
        "trade_count": 100.0,
        "execution_cost_impact": 0.02,
    }


def _risk_run(
    dates: pd.DatetimeIndex,
    exposure: list[float],
) -> RiskLayerRun:
    """构造只用于触发路径诊断的最小风险层结果。"""
    values = pd.Series(range(100, 100 + len(dates)), index=dates, dtype=float)
    return RiskLayerRun(
        result=BacktestResearchResult(
            strategy="test",
            daily_values=values,
            trades=[],
            failed_orders=[],
            total_cost=0.0,
            turnover_notional=0.0,
        ),
        exposure=pd.Series(exposure, index=dates),
        events=pd.DataFrame(),
    )
