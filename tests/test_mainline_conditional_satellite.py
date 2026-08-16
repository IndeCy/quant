"""主线链动条件式卫星测试。"""

from __future__ import annotations

import pandas as pd

from examples import mainline_conditional_satellite_study as study


def _common() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": [
                "20240102",
                "20240103",
                "20240104",
                "20240105",
            ],
            "nav_core": [1.0, 1.01, 1.02, 1.03],
            "nav_satellite": [1.0, 1.02, 1.04, 1.06],
            "benchmark_nav": [1.0, 1.0, 1.0, 1.0],
        }
    )


def test_conditional_satellite_only_activates_in_frozen_regime() -> None:
    """只有 RISK_POSITIVE 状态才允许卫星占30%。"""
    regimes = pd.DataFrame(
        {
            "trade_date": _common()["trade_date"],
            "state_asof_date": [
                "20231229",
                "20240102",
                "20240103",
                "20240104",
            ],
            "regime": [
                "UP_POSITIVE",
                "RISK_POSITIVE",
                "RISK_POSITIVE",
                "UP_NONPOSITIVE",
            ],
        }
    )

    result = study.simulate_conditional_allocation(
        _common(),
        regimes,
        cost_bps=10.0,
    )
    rows = result.daily.set_index("trade_date")

    assert rows.loc["20240102", "satellite_weight_open"] == 0.0
    assert rows.loc["20240103", "satellite_weight_open"] == 0.30
    assert rows.loc["20240104", "satellite_weight_open"] > 0.30
    assert rows.loc["20240105", "satellite_weight_open"] == 0.0
    assert result.transition_count == 2


def test_conditional_transition_charges_allocation_cost() -> None:
    """状态切换必须产生组合级换手和调拨成本。"""
    regimes = pd.DataFrame(
        {
            "trade_date": _common()["trade_date"],
            "state_asof_date": [
                "20231229",
                "20240102",
                "20240103",
                "20240104",
            ],
            "regime": [
                "UP_POSITIVE",
                "RISK_POSITIVE",
                "RISK_POSITIVE",
                "UP_NONPOSITIVE",
            ],
        }
    )

    result = study.simulate_conditional_allocation(
        _common(),
        regimes,
        cost_bps=10.0,
    )

    assert result.total_cost > 0
    assert result.daily["allocation_turnover"].sum() > 0
    assert result.daily.iloc[-1]["portfolio_nav"] < result.daily.iloc[-1][
        "gross_nav"
    ]


def test_gate_cannot_grant_production_registration() -> None:
    """历史门槛通过也必须保留前向验证标记。"""
    item = {
        "annualized_return": 0.15,
        "max_drawdown": -0.10,
        "sharpe": 1.2,
        "calmar": 1.5,
        "excess_return": 0.2,
        "annual_turnover": 1.0,
        "annualized_cost_drag": 0.005,
    }
    core = {**item, "annualized_return": 0.12, "sharpe": 1.0}
    fixed = {**item, "annualized_return": 0.13, "sharpe": 1.1}
    metrics = {
        name: {
            "conditional": dict(item),
            "core": dict(core),
            "fixed_70_30": dict(fixed),
        }
        for name in [*study.FOLDS, "full"]
    }

    gate = study.evaluate_gate(metrics, 0.20)

    assert gate["passed"] is True
    assert gate["selection_bias_requires_forward_test"] is True


def test_period_metrics_preserves_fixed_allocation_turnover() -> None:
    """固定70/30对照不能把真实月度调拨换手展示成0。"""
    daily = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103"],
            "portfolio_nav": [1.0, 1.01],
            "gross_nav": [1.0, 1.01],
            "fixed_nav": [1.0, 1.01],
            "core_nav": [1.0, 1.01],
            "benchmark_nav": [1.0, 1.0],
            "allocation_turnover": [0.0, 0.01],
            "fixed_allocation_turnover": [0.0, 0.02],
        }
    )

    result = study.build_period_metrics(
        daily,
        {"full": ("20240102", "20240103")},
    )

    assert result["full"]["conditional"]["annual_turnover"] == 2.52
    assert result["full"]["fixed_70_30"]["annual_turnover"] == 5.04


def test_cached_attempt_skips_conditional_calculation(monkeypatch) -> None:
    """相同运行指纹存在时不得再次组合历史净值。"""

    class CachedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: CachedAttempt(),
    )
    monkeypatch.setattr(study, "_data_version", lambda paths: "test")
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("不应执行计算")
        ),
    )

    result = study.run_study(object(), "20260724")  # type: ignore[arg-type]

    assert result == {"reused": True}
