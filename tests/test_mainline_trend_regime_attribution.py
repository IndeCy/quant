"""主线链动趋势状态归因测试。"""

from __future__ import annotations

import pandas as pd

from examples import mainline_trend_regime_attribution_metrics as metrics
from examples import mainline_trend_regime_attribution_study as study


def test_regime_is_lagged_one_trading_day() -> None:
    """T 日收盘状态只能解释 T+1 收益。"""
    market = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103", "20240104"],
            "benchmark_nav": [1.0, 1.1, 1.2],
            "trend_state": ["UP", "UP", "RISK"],
        }
    )

    result = metrics.classify_lagged_trend_regime(
        market,
        return_window=1,
    ).set_index("trade_date")

    assert result.loc["20240104", "state_asof_date"] == "20240103"
    assert result.loc["20240104", "regime"] == "UP_POSITIVE"


def test_regime_metrics_reports_conditional_performance() -> None:
    """条件指标必须分别保留核心、卫星和组合表现。"""
    daily = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103", "20240104"],
            "regime": ["UP_POSITIVE", "UP_POSITIVE", "RISK_POSITIVE"],
            "core_return": [0.01, 0.01, -0.01],
            "satellite_return": [0.02, 0.03, -0.02],
            "combined_return_net": [0.013, 0.016, -0.013],
        }
    )

    result = metrics.build_regime_metrics(
        daily,
        {"full": ("20240102", "20240104")},
    )
    up = result[result["regime"] == "UP_POSITIVE"].iloc[0]

    assert up["days"] == 2
    assert up["satellite_total_return"] > up["core_total_return"]
    assert "combined_max_drawdown" in result.columns


def test_candidate_gate_rejects_cross_fold_instability() -> None:
    """全样本漂亮但任一阶段为负时不得进入条件式研究。"""
    rows = []
    for period, total_return in [
        ("fold_a", 0.1),
        ("fold_b", -0.01),
        ("full", 0.3),
    ]:
        rows.append(
            {
                "period": period,
                "regime": "UP_POSITIVE",
                "days": 200,
                "satellite_total_return": total_return,
                "satellite_annualized_return": 0.2,
                "satellite_sharpe": 1.0,
                "satellite_annual_lift_vs_core": 0.1,
                "satellite_max_drawdown": -0.1,
            }
        )
    episode_rows = [
        {
            "regime": "UP_POSITIVE",
            "days": 5,
            "satellite_return": 0.01,
        }
        for _ in range(5)
    ]

    gate = metrics.evaluate_regime_candidates(
        pd.DataFrame(rows),
        pd.DataFrame(episode_rows),
        ["fold_a", "fold_b"],
    )

    assert gate["UP_POSITIVE"]["passed"] is False
    assert (
        gate["UP_POSITIVE"]["checks"]["all_folds_positive"] is False
    )


def test_cached_attempt_skips_calculation(monkeypatch) -> None:
    """相同指纹已有成功结果时不得再次读取历史和计算。"""

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
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("不应执行计算")
        ),
    )
    monkeypatch.setattr(study, "_data_version", lambda paths: "test")

    result = study.run_study(
        object(),  # type: ignore[arg-type]
        "20260724",
    )

    assert result == {"reused": True}
