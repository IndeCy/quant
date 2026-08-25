"""五资产双动量研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.fund_portfolio import load_fund_portfolio_panel
from examples import cross_asset_dual_momentum_study as study
from factors.etf_momentum import calculate_trailing_momentum
from portfolio.defensive_rotation import build_defensive_rotation_targets


def test_fund_panel_merges_increment_and_applies_asof_qfq(tmp_path: Path) -> None:
    """增量覆盖同日基线，qfq 只能使用截止日最后因子。"""
    history = tmp_path / "history.duckdb"
    increment = tmp_path / "increment.duckdb"
    with duckdb.connect(str(history)) as connection:
        connection.execute(
            """
            CREATE TABLE etf_lof_reits_daily_adj(
                ts_code VARCHAR, trade_date VARCHAR,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                vol DOUBLE, amount DOUBLE, adj_factor DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO etf_lof_reits_daily_adj VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("A", "20240102", 10, 11, 9, 10, 100, 1000, 1.0),
                ("A", "20240103", 10, 11, 9, 10, 100, 1000, 2.0),
                ("B", "20240102", 20, 21, 19, 20, 100, 1000, 1.0),
                ("B", "20240103", 20, 21, 19, 20, 100, 1000, 1.0),
            ],
        )
    with duckdb.connect(str(increment)) as connection:
        connection.execute(
            "CREATE TABLE fund_daily(ts_code VARCHAR, trade_date VARCHAR, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, "
            "vol DOUBLE, amount DOUBLE)"
        )
        connection.execute(
            "CREATE TABLE fund_adj(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)"
        )
        connection.execute(
            "INSERT INTO fund_daily VALUES ('A','20240103',12,13,11,12,200,2000)"
        )
        connection.execute(
            "INSERT INTO fund_adj VALUES ('A','20240103',2.0)"
        )

    panel = load_fund_portfolio_panel(
        history,
        increment,
        ["A", "B"],
        start_date="20240101",
        end_date="20240103",
    )

    assert panel.latest_common_date == "20240103"
    assert panel.bars.loc[(pd.Timestamp("2024-01-03"), "A"), "close"] == 12.0
    assert panel.bars.loc[(pd.Timestamp("2024-01-02"), "A"), "close"] == 5.0


def test_momentum_does_not_use_prices_after_signal_date() -> None:
    """修改信号日之后价格不得改变该信号分数。"""
    dates = pd.bdate_range("2023-01-02", periods=254)
    close = pd.DataFrame(
        {"A": range(100, 354), "B": range(200, 454)},
        index=dates,
    )
    signal = dates[252]
    original = calculate_trailing_momentum(close, [signal], ["A", "B"])
    modified = close.copy()
    modified.loc[dates[253], "A"] = 99999

    repeated = calculate_trailing_momentum(modified, [signal], ["A", "B"])

    pd.testing.assert_frame_equal(original, repeated)


def test_rotation_uses_positive_top_two_and_bond_fill() -> None:
    """只有一个正动量资产时，另一半必须进入国债。"""
    scores = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 4,
            "symbol": ["A", "B", "C", "D"],
            "factor_score": [0.20, -0.10, -0.20, -0.30],
        }
    )

    targets, holdings = build_defensive_rotation_targets(
        scores,
        ["A", "B", "C", "D"],
        "BOND",
        top_n=2,
    )

    assert targets["20240131"] == {"A": 0.5, "BOND": 0.5}
    assert set(holdings["role"]) == {"risk_asset", "defensive_fill"}


def test_rotation_holds_bond_when_all_risky_assets_are_negative() -> None:
    """风险资产绝对动量全负时必须100%配置防守资产。"""
    scores = pd.DataFrame(
        {
            "signal_date": ["20240131", "20240131"],
            "symbol": ["A", "B"],
            "factor_score": [-0.01, -0.20],
        }
    )

    targets, _ = build_defensive_rotation_targets(
        scores,
        ["A", "B"],
        "BOND",
        top_n=2,
    )

    assert targets["20240131"] == {"BOND": 1.0}


def test_fixed_gate_rejects_high_quality_correlation() -> None:
    """收益和回撤合格但与核心高度相关时不能晋级。"""
    good = _metrics()
    metrics = {key: good for key in [*study.FOLDS, "full"]}

    gate = study.evaluate_gate(metrics, quality_correlation=0.85)

    assert gate["passed"] is False
    assert gate["checks"]["quality_correlation_at_most_060"] is False


def test_etf_execution_model_has_no_stamp_tax() -> None:
    """ETF 卖出不应错误收取股票印花税。"""
    model = study._execution_model()
    assert model.stamp_tax_rate == 0.0
    assert model.execution_lag == 1


def test_research_reuses_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同数据和固定策略定义不能再次扫描基金大表。"""

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


def _metrics() -> dict[str, float]:
    return {
        "annualized_return": 0.08,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.40,
        "excess_return": 0.10,
        "annual_turnover": 2.0,
        "trade_count": 20.0,
        "execution_cost_impact": 0.01,
    }
