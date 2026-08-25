"""全球防守三资产正式研究测试。"""

from __future__ import annotations

import pandas as pd

from examples import global_defensive_equal_study as study


def _metrics() -> dict[str, dict[str, float]]:
    """构造满足绝对门槛的四折和全区间指标。"""
    return {
        key: {
            "annualized_return": 0.08,
            "max_drawdown": -0.18,
            "sharpe": 0.80,
            "calmar": 0.44,
            "excess_return": 0.10,
            "annual_turnover": 0.40,
        }
        for key in [*study.FOLDS, "full"]
    }


def _annual() -> dict[str, dict[str, float]]:
    return {
        str(year): {"annualized_return": 0.04}
        for year in range(2015, 2027)
    }


def _correlations(value: float = 0.20) -> dict[str, dict[str, float]]:
    symbols = list(study.ASSET_WEIGHTS)
    return {
        left: {
            right: 1.0 if left == right else value
            for right in symbols
        }
        for left in symbols
    }


def _comparisons() -> dict[str, dict[str, float]]:
    full = _metrics()["full"]
    return {
        study.STRATEGY_ID: full,
        "黄金国债50/50": {
            **full,
            "annualized_return": 0.07,
        },
        "标普500单资产": {
            **full,
            "max_drawdown": -0.30,
        },
        "沪深300单资产": full,
    }


def test_definition_is_fixed_equal_weight_without_overlay() -> None:
    """三只资产、月频等权和无覆盖层不得在回测后改变。"""
    definition = study.RESEARCH_SPEC.definition

    assert set(definition["asset_allocation"]) == {
        "513500.SH",
        "518880.SH",
        "511010.SH",
    }
    assert all(
        abs(weight - 1.0 / 3.0) < 1e-12
        for weight in definition["asset_allocation"].values()
    )
    assert definition["portfolio"]["rebalance"] == "monthly"
    assert definition["risk_overlay"] == "none"


def test_targets_keep_fixed_weights_for_every_signal() -> None:
    """所有调仓日必须使用同一组冻结权重。"""
    dates = [pd.Timestamp("2026-01-30"), pd.Timestamp("2026-02-27")]

    targets = study._build_targets(dates, study.ASSET_WEIGHTS)

    assert set(targets) == {"20260130", "20260227"}
    assert all(weights == study.ASSET_WEIGHTS for weights in targets.values())


def test_gate_passes_complete_independent_candidate() -> None:
    """绝对表现、稳定性和独立性都达标时才允许前瞻观察。"""
    gate = study.evaluate_gate(
        _metrics(),
        _annual(),
        0.20,
        _correlations(),
        _comparisons(),
    )

    assert gate["passed"] is True


def test_gate_rejects_high_quality_correlation() -> None:
    """与现有Quality高度同步时不构成新的独立收益来源。"""
    gate = study.evaluate_gate(
        _metrics(),
        _annual(),
        0.60,
        _correlations(),
        _comparisons(),
    )

    assert gate["passed"] is False
    assert gate["checks"]["quality_correlation_at_most_030"] is False


def test_gate_rejects_correlated_asset_sleeves() -> None:
    """底层资产同涨同跌时不得把等权包装成分散化。"""
    gate = study.evaluate_gate(
        _metrics(),
        _annual(),
        0.20,
        _correlations(0.70),
        _comparisons(),
    )

    assert gate["passed"] is False
    assert (
        gate["checks"]["pairwise_asset_correlation_at_most_050"]
        is False
    )
