"""低60日收益偏度研究的点时与指纹测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.return_skewness import (
    materialize_return_skewness_features,
)
from examples import low_return_skewness_study as study
from examples.low_return_skewness_support import (
    build_execution_attribution,
    build_monthly_coverage,
    diagnose_execution_attribution,
)
from factors.return_skewness import score_low_return_skewness_frame
from runtime.paths import RuntimePaths
from runtime.research_attempts import complete_research_attempt


def test_rolling_skewness_uses_only_current_and_past_returns() -> None:
    """追加未来极端收益不能改变历史第60日偏度。"""
    connection = duckdb.connect(":memory:")
    dates = pd.bdate_range("2020-01-01", periods=61)
    returns = [((index % 7) - 3) / 100 for index in range(60)]
    connection.execute(
        "CREATE TABLE features(trade_date VARCHAR, symbol VARCHAR, ret DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO features VALUES (?, 'TEST', ?)",
        [
            (date.strftime("%Y%m%d"), value)
            for date, value in zip(dates[:60], returns)
        ],
    )
    try:
        table = materialize_return_skewness_features(connection, window=60)
        before = connection.execute(
            f"SELECT return_skewness_60d FROM {table} "
            "WHERE trade_date = ?",
            [dates[59].strftime("%Y%m%d")],
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO features VALUES (?, 'TEST', 9.0)",
            [dates[60].strftime("%Y%m%d")],
        )
        materialize_return_skewness_features(connection, window=60)
        after = connection.execute(
            f"SELECT return_skewness_60d FROM {table} "
            "WHERE trade_date = ?",
            [dates[59].strftime("%Y%m%d")],
        ).fetchone()[0]
    finally:
        connection.close()

    assert before == after


def test_factor_scores_lower_skewness_higher() -> None:
    """负偏或低偏股票必须获得更高横截面得分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["NEG", "FLAT", "POS"],
            "return_skewness_60d": [-1.0, 0.0, 2.0],
        }
    )

    scored = score_low_return_skewness_frame(frame).set_index("symbol")

    assert scored.loc["NEG", "factor_score"] > scored.loc["FLAT", "factor_score"]
    assert scored.loc["FLAT", "factor_score"] > scored.loc["POS", "factor_score"]


def test_monthly_coverage_keeps_missing_skewness_in_denominator() -> None:
    """不足60日的股票必须留在可投分母中。"""
    panel = pd.DataFrame(
        {
            "signal_date": ["20220131"] * 4,
            "symbol": ["A", "B", "C", "D"],
            "return_skewness_60d": [-0.2, 0.1, None, None],
        }
    )

    row = build_monthly_coverage(panel).iloc[0]

    assert row["investable_count"] == 4
    assert row["candidate_count"] == 2
    assert row["coverage"] == 0.5


def test_research_definition_has_no_parameter_search() -> None:
    """窗口、TopN和模型口径必须在正式计算前冻结。"""
    definition = study.RESEARCH_SPEC.definition

    assert definition["factor"] == {
        "formula": "sample_skewness(qfq_daily_return_trailing_60d)",
        "direction": "lower_is_better",
        "window": 60,
        "transform": "raw_cross_sectional_percentile_rank_no_winsorize",
    }
    assert definition["portfolio"]["top_n"] == 40
    assert definition["risk_overlay"]["scheme"] == "GRID"
    assert study.RISK_SCHEME == "GRID"
    assert definition["evaluation"]["no_window_or_topn_search"] is True
    assert "low_max" in definition["prior_research_distinction"]


def test_execution_attribution_compares_same_periods() -> None:
    """执行归因只比较同区间净值与零摩擦反事实。"""
    net = {
        "locked_test": {
            "annualized_return": 0.06,
            "sharpe": 0.40,
            "max_drawdown": -0.27,
        }
    }
    frictionless = {
        "locked_test": {
            "annualized_return": 0.09,
            "sharpe": 0.55,
            "max_drawdown": -0.25,
        }
    }

    result = build_execution_attribution(net, frictionless)["locked_test"]

    assert result["annualized_return_drag"] == 0.03
    assert result["sharpe_drag"] == pytest.approx(0.15)
    assert result["net_max_drawdown"] == -0.27


def test_execution_diagnosis_rejects_weak_frictionless_signal() -> None:
    """零摩擦下仍不达标时不能误判为单纯执行负Alpha。"""
    attribution = {
        "locked_test": {
            "frictionless_annualized_return": 0.09,
            "frictionless_sharpe": 0.48,
            "frictionless_max_drawdown": -0.26,
            "annualized_return_drag": 0.02,
        },
        "full": {
            "frictionless_annualized_return": 0.08,
            "frictionless_sharpe": 0.44,
            "frictionless_max_drawdown": -0.64,
            "annualized_return_drag": 0.02,
        },
    }

    result = diagnose_execution_attribution(attribution)

    assert result["classification"] == "WEAK_GROSS_SIGNAL_WITH_COST_DRAG"
    assert result["frictionless_passed_core_gate"] is False


def test_same_fingerprint_skips_market_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同语义与数据快照必须复用，不能再次扫描日线。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.base_market_path,
        paths.live_market_increment_path,
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.monitoring_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260726",
        data_version=study._data_version(paths),
    )
    complete_research_attempt(
        attempt,
        metrics={"decision": "REJECTED"},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不得扫描行情")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260726")

    assert result["reused"] is True
