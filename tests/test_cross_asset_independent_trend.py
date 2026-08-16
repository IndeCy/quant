"""跨资产独立趋势因子、组合和门禁测试。"""

from __future__ import annotations

import pandas as pd

from examples import cross_asset_independent_trend_feasibility_study as study
from factors.etf_independent_trend import calculate_independent_trend_states
from portfolio.independent_trend_slots import build_independent_trend_slot_targets


def test_trend_state_uses_signal_day_and_prior_prices_only() -> None:
    """未来价格变化不能反向改变当前月末趋势状态。"""
    index = pd.date_range("2023-01-01", periods=140, freq="B")
    close = pd.DataFrame(
        {"A": range(1, 141)},
        index=index,
        dtype=float,
    )
    signal = index[125]
    original = calculate_independent_trend_states(close, [signal], ["A"])
    close.loc[index[126]:, "A"] = 1.0
    changed_future = calculate_independent_trend_states(close, [signal], ["A"])

    assert original.to_dict("records") == changed_future.to_dict("records")
    assert bool(original.iloc[0]["trend_active"]) is True


def test_inactive_slots_redirect_to_defensive_asset() -> None:
    """四个风险槽位中两个关闭时，国债应获得50%权重。"""
    states = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 4,
            "symbol": ["A", "B", "C", "D"],
            "trend_active": [True, False, True, False],
            "ma60": [2.0, 1.0, 2.0, 1.0],
            "ma120": [1.0, 2.0, 1.0, 2.0],
        }
    )

    targets, _ = build_independent_trend_slot_targets(
        states,
        ["A", "B", "C", "D"],
        "BOND",
    )

    assert targets["20240131"] == {"A": 0.25, "C": 0.25, "BOND": 0.5}


def test_feasibility_rejects_degenerate_always_on_signal() -> None:
    """趋势状态若长期恒定，就没有可验证的状态切换能力。"""
    coverage = [
        {
            "symbol": symbol,
            "start_date": "20130101",
            "end_date": "20260724",
            "row_count": 100,
        }
        for symbol in study.RISKY_ASSETS + [study.DEFENSIVE_ASSET]
    ]
    states = pd.DataFrame(
        [
            {
                "signal_date": "20260630",
                "symbol": symbol,
                "close": 2.0,
                "ma60": 2.0,
                "ma120": 1.0,
                "trend_active": True,
            }
            for symbol in study.RISKY_ASSETS
        ]
    )
    targets = {"20260630": {symbol: 0.25 for symbol in study.RISKY_ASSETS}}

    result = study.evaluate_feasibility(
        coverage,
        list(pd.date_range("2026-01-01", periods=100, freq="B")),
        states,
        targets,
        [pd.Timestamp("20260630")],
        "20260724",
        "20260726",
    )

    assert result["passed"] is False
    assert result["checks"]["states_are_not_degenerate"] is False


def test_formal_gate_requires_drawdown_improvement() -> None:
    """候选必须实质修复双动量尾部回撤，不能只靠收益通过。"""
    from examples import cross_asset_independent_trend_study as formal

    candidate = {
        key: {
            "annualized_return": 0.08,
            "max_drawdown": -0.20,
            "sharpe": 0.70,
            "calmar": 0.40,
            "excess_return": 0.10,
            "annual_turnover": 2.0,
        }
        for key in [*formal.FOLDS, "full"]
    }
    delta = {
        "full_drawdown_improvement": 0.14,
        "early_drawdown_improvement": 0.20,
        "annual_return_change": -0.01,
        "sharpe_change": 0.10,
    }

    gate = formal.evaluate_gate(candidate, 0.30, delta)

    assert gate["passed"] is False
    assert gate["checks"]["dual_full_drawdown_improves_15pct"] is False


def test_formal_strategy_has_no_extra_risk_overlay() -> None:
    """趋势信号本身控制暴露，不得暗中叠加旧波动率参数。"""
    from examples import cross_asset_independent_trend_study as formal

    assert (
        formal.RESEARCH_SPEC.definition["risk_overlay"]
        == "none_signal_itself_controls_asset_exposure"
    )
