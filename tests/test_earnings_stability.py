"""五年盈利稳定性因子和数据门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import earnings_stability_feasibility_study as study
from examples import earnings_stability_study as strategy_study
from factors.earnings_stability import score_earnings_stability_frame


def test_factor_prefers_lower_roa_variability() -> None:
    """五年平均盈利均为正时，ROA 波动更小者得分更高。"""
    frame = pd.DataFrame(
        {
            "symbol": ["STABLE", "VOLATILE"],
            "roa_std_5y": [1.0, 4.0],
            "roa_mean_5y": [3.0, 8.0],
            "observations": [5, 5],
        }
    )

    scored = score_earnings_stability_frame(frame).set_index("symbol")

    assert scored.loc["STABLE", "factor_score"] > scored.loc[
        "VOLATILE", "factor_score"
    ]


def test_factor_excludes_stable_losses_and_incomplete_history() -> None:
    """稳定亏损和不足五期的公司不得进入排序。"""
    frame = pd.DataFrame(
        {
            "symbol": ["PROFIT", "LOSS", "SHORT"],
            "roa_std_5y": [1.0, 0.1, 0.2],
            "roa_mean_5y": [2.0, -1.0, 3.0],
            "observations": [5, 5, 4],
        }
    )

    result = score_earnings_stability_frame(frame)

    assert result["symbol"].tolist() == ["PROFIT"]


def test_feasibility_rejects_sparse_or_degenerate_months() -> None:
    """候选不足或因子大量并列时不得进入收益回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20231229", "20240131", "20240229"],
            "candidate_count": [1000, 500, 1000],
            "unique_factor_values": [900, 400, 900],
            "zero_std_share": [0.01, 0.20, 0.01],
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {
            "std_p01": 0.1,
            "std_median": 1.0,
            "std_p99": 10.0,
            "mean_roa_median": 4.0,
            "current_roa_median": 4.0,
        },
        {
            "duplicate_signal_symbol_rows": 0,
            "visibility_violations": 0,
            "observation_count_violations": 0,
            "median_spearman_score_with_mean_roa": 0.1,
        },
        "20240229",
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_feasibility_reuses_fingerprint_without_data_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义与数据版本必须复用，不得再次扫描财务大表。"""
    filenames = [
        "daily_adj_19901219_20260615.duckdb",
        "fina_indicator.duckdb",
        "income.duckdb",
        "balancesheet.duckdb",
        "cashflow.duckdb",
    ]
    for filename in filenames:
        (tmp_path / filename).write_bytes(b"fixture")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "experiment_id": study.EXPERIMENT_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应读取研究数据"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_formal_gate_rejects_quality_redundancy() -> None:
    """业绩合格但与 Quality 同源时仍不得晋级。"""
    good = _good_metrics()
    metrics = {
        "2015_2017": good,
        "2018_2020": good,
        "2021_2023": good,
        "2024_latest": good,
        "full": good,
    }

    result = strategy_study.evaluate_gate(metrics, quality_correlation=0.90)

    assert result["passed"] is False
    assert result["checks"]["quality_correlation_at_most_075"] is False


def test_strategy_reuses_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """正式研究相同指纹必须复用，不得再次启动回测。"""
    filenames = [
        "daily_adj_19901219_20260615.duckdb",
        "fina_indicator.duckdb",
        "income.duckdb",
        "balancesheet.duckdb",
        "cashflow.duckdb",
    ]
    for filename in filenames:
        (tmp_path / filename).write_bytes(b"fixture")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {
                "reused": True,
                "strategy_id": strategy_study.STRATEGY_ID,
            }

    monkeypatch.setattr(
        strategy_study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        strategy_study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新回测"),
    )

    result = strategy_study.run_study(
        strategy_study.RuntimePaths(tmp_path),
        "20260726",
    )

    assert result["reused"] is True


def _good_metrics() -> dict[str, float]:
    """构造一组通过四折收益与风险门槛的指标。"""
    return {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.10,
        "annual_turnover": 6.0,
        "trade_count": 20.0,
        "execution_cost_impact": 0.01,
    }
