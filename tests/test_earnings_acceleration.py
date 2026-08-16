"""业绩快报利润增长加速度研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.earnings_express import (
    EarningsExpressPaths,
    attach_earnings_express_database,
    create_earnings_express_signal_date_table,
    load_earnings_acceleration_snapshot,
    materialize_earnings_acceleration_asof,
)
from examples import earnings_express_acceleration_study as study
from examples import earnings_express_acceleration_v2_study as study_v2
from factors.earnings_acceleration import (
    score_earnings_acceleration_frame,
    score_persistent_earnings_acceleration_frame,
)


def _create_express_db(path: Path) -> None:
    """创建包含连续年度快报和未来公告的最小数据集。"""
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE default_table (
            ts_code VARCHAR,
            end_date VARCHAR,
            ann_date VARCHAR,
            n_income DOUBLE,
            yoy_net_profit DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO default_table VALUES (?, ?, ?, ?, ?)",
        [
            ("000001.SZ", "20181231", "20190215", 100, 80),
            ("000001.SZ", "20191231", "20200215", 150, 100),
            ("000001.SZ", "20201231", "20210415", 240, 150),
            ("000002.SZ", "20191231", "20200220", 120, 100),
        ],
    )
    connection.close()


def test_express_asof_derives_growth_and_blocks_future_announcement(
    tmp_path: Path,
) -> None:
    """只能使用信号日前已公告的连续年度快报。"""
    database = tmp_path / "express.duckdb"
    _create_express_db(database)
    connection = duckdb.connect()
    try:
        create_earnings_express_signal_date_table(connection, ["20210331"])
        attach_earnings_express_database(connection, EarningsExpressPaths(database))
        materialize_earnings_acceleration_asof(connection)
        snapshot = load_earnings_acceleration_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["symbol"].tolist() == ["000001.SZ"]
    row = snapshot.iloc[0]
    assert row["fiscal_year"] == 2019
    assert row["prior_year_net_income"] == pytest.approx(100)
    assert row["profit_growth"] == pytest.approx(0.50)
    assert row["prior_profit_growth"] == pytest.approx(0.25)
    assert row["profit_acceleration"] == pytest.approx(0.25)


def test_acceleration_factor_requires_positive_growth_and_acceleration() -> None:
    """利润下降、减速或亏损样本不能进入候选。"""
    frame = pd.DataFrame(
        [
            _factor_row("FAST", 0.50, 0.10),
            _factor_row("SLOW", 0.20, 0.15),
            _factor_row("DECEL", 0.10, 0.20),
            _factor_row("LOSS", -0.20, -0.40, current=-10),
        ]
    )

    result = score_earnings_acceleration_frame(frame)

    assert set(result["symbol"]) == {"FAST", "SLOW"}
    assert result.iloc[0]["symbol"] == "FAST"
    assert result.iloc[0]["factor_score"] > result.iloc[1]["factor_score"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同快报数据与定义必须直接复用历史研究。"""
    (tmp_path / "express.duckdb").write_bytes(b"test")

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
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def test_fixed_gate_rejects_insufficient_locked_sharpe() -> None:
    """锁定期Sharpe不足时不能进入生产确认。"""
    good = {
        "annualized_return": 0.12,
        "max_drawdown": -0.25,
        "sharpe": 0.8,
        "calmar": 0.48,
        "excess_return": 0.2,
        "annual_turnover": 4.0,
        "trade_count": 100.0,
        "execution_cost_impact": 0.01,
    }
    metrics = {
        "locked_test": {**good, "sharpe": 0.4},
        "full": good,
    }
    annual = {str(year): good for year in range(2015, 2027)}

    gate = study.evaluate_gate(metrics, annual, 0.3)

    assert gate["passed"] is False
    assert gate["checks"]["locked_test_sharpe_at_least_055"] is False


def test_persistent_acceleration_requires_prior_positive_growth() -> None:
    """V2必须排除上一年度仍在衰退的低基数恢复样本。"""
    frame = pd.DataFrame(
        [
            _factor_row("PERSISTENT", 0.50, 0.10),
            _factor_row("RECOVERY", 0.50, -0.80),
        ]
    )

    result = score_persistent_earnings_acceleration_frame(frame)

    assert result["symbol"].tolist() == ["PERSISTENT"]


def test_v2_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V2相同指纹再次运行时不能重复回测。"""
    (tmp_path / "express.duckdb").write_bytes(b"test")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study_v2.STRATEGY_ID}

    monkeypatch.setattr(
        study_v2,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study_v2,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = study_v2.run_study(study_v2.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _factor_row(
    symbol: str,
    growth: float,
    prior_growth: float,
    *,
    current: float = 150,
) -> dict[str, object]:
    """生成一条因子输入。"""
    return {
        "symbol": symbol,
        "signal_date": "20210331",
        "current_net_income": current,
        "prior_year_net_income": 100,
        "profit_growth": growth,
        "prior_profit_growth": prior_growth,
        "profit_acceleration": growth - prior_growth,
    }
