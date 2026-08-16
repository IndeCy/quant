"""连续现金分红增长研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.dividend_events import (
    DividendEventPaths,
    attach_dividend_database,
    create_dividend_signal_date_table,
    load_dividend_growth_snapshot,
    materialize_dividend_growth_asof,
)
from examples import dividend_growth_persistence_study as study
from examples import dividend_growth_persistence_v2_study as study_v2
from examples import dividend_growth_persistence_v3_study as study_v3
from factors.dividend_growth import (
    score_dividend_growth_frame,
    score_dividend_growth_rank_frame,
)


def _create_dividend_db(path: Path) -> None:
    """创建包含实施、预案、多次派息和未来除息的最小数据集。"""
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE dividend (
            ts_code VARCHAR,
            end_date VARCHAR,
            ann_date VARCHAR,
            div_proc VARCHAR,
            cash_div_tax DOUBLE,
            ex_date VARCHAR,
            base_share DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO dividend VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("000001.SZ", "20171231", "20180301", "实施", 0.10, "20180601", 100),
            ("000001.SZ", "20181231", "20190301", "实施", 0.12, "20190601", 100),
            ("000001.SZ", "20191231", "20200301", "实施", 0.08, "20200601", 100),
            ("000001.SZ", "20191231", "20200401", "实施", 0.07, "20200701", 100),
            ("000001.SZ", "20201231", "20210301", "实施", 0.20, "20210801", 100),
            ("000002.SZ", "20191231", "20200301", "预案", 1.00, None, 100),
        ],
    )
    connection.close()


def test_dividend_asof_aggregates_visible_annual_cash_and_blocks_future(
    tmp_path: Path,
) -> None:
    """同年多次已除息派息应求和，未来除息和预案不可见。"""
    database = tmp_path / "dividend.duckdb"
    _create_dividend_db(database)
    connection = duckdb.connect()
    try:
        create_dividend_signal_date_table(connection, ["20200731"])
        attach_dividend_database(connection, DividendEventPaths(database))
        materialize_dividend_growth_asof(connection)
        snapshot = load_dividend_growth_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["symbol"].tolist() == ["000001.SZ"]
    row = snapshot.iloc[0]
    assert row["latest_fiscal_year"] == 2019
    assert row["cash_payout_y0"] == pytest.approx(15.0)
    assert row["cash_payout_y1"] == pytest.approx(12.0)
    assert row["cash_payout_y2"] == pytest.approx(10.0)


def test_dividend_growth_factor_uses_weaker_of_two_growth_rates() -> None:
    """持续温和增长应优于单年暴增后停滞。"""
    frame = pd.DataFrame(
        [
            _factor_row("STABLE", 144, 120, 100),
            _factor_row("SPIKE", 200, 200, 100),
            _factor_row("CUT", 90, 100, 80),
        ]
    )

    result = score_dividend_growth_frame(frame)

    assert set(result["symbol"]) == {"STABLE", "SPIKE"}
    stable = result.set_index("symbol").loc["STABLE"]
    spike = result.set_index("symbol").loc["SPIKE"]
    assert stable["dividend_growth_floor"] == pytest.approx(0.20)
    assert spike["dividend_growth_floor"] == pytest.approx(0.0)
    assert stable["factor_score"] > spike["factor_score"]


def test_dividend_growth_factor_requires_all_columns() -> None:
    """缺少点时分红字段时必须显式失败。"""
    with pytest.raises(ValueError, match="cash_payout_y2"):
        score_dividend_growth_frame(
            pd.DataFrame(
                {
                    "symbol": ["A"],
                    "signal_date": ["20200131"],
                    "cash_payout_y0": [1],
                    "cash_payout_y1": [1],
                }
            )
        )


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """命中历史指纹后不应重新读取行情和执行回测。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "dividend_increment.duckdb").write_bytes(b"test")

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


def test_fixed_gate_rejects_high_turnover() -> None:
    """换手超过冻结门槛时不能进入生产确认。"""
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
        "locked_test": good,
        "full": {**good, "annual_turnover": 9.0},
    }
    annual = {str(year): good for year in range(2017, 2027)}

    gate = study.evaluate_gate(metrics, annual, 0.3)

    assert gate["passed"] is False
    assert gate["checks"]["annual_turnover_below_8x"] is False


def test_v2_requires_recent_annual_dividend_history() -> None:
    """V2只能保留信号年前1至2个财年的最新分红。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20260630"] * 4,
            "latest_fiscal_year": [2025, 2024, 2023, 2026],
            "symbol": ["AGE1", "AGE2", "STALE", "CURRENT"],
        }
    )

    result = study_v2.apply_recent_dividend_history(frame)

    assert set(result["symbol"]) == {"AGE1", "AGE2"}
    assert set(result["latest_fiscal_year_age"]) == {1, 2}


def test_v2_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V2相同指纹必须复用，不能借版本名重复回测。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "dividend_increment.duckdb").write_bytes(b"test")

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


def test_v3_rank_mapping_keeps_distinct_top_growth_scores() -> None:
    """百分位映射不能把不同的头部增长率截成同分。"""
    frame = pd.DataFrame(
        [
            _factor_row("HIGH", 300, 150, 100),
            _factor_row("MID", 180, 120, 100),
            _factor_row("LOW", 121, 110, 100),
        ]
    )

    result = score_dividend_growth_rank_frame(frame).set_index("symbol")

    assert result.loc["HIGH", "factor_score"] > result.loc["MID", "factor_score"]
    assert result.loc["MID", "factor_score"] > result.loc["LOW", "factor_score"]


def test_v3_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V3相同数据与定义再次运行时必须直接复用。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "dividend_increment.duckdb").write_bytes(b"test")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study_v3.STRATEGY_ID}

    monkeypatch.setattr(
        study_v3,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study_v3,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = study_v3.run_study(study_v3.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _factor_row(
    symbol: str,
    y0: float,
    y1: float,
    y2: float,
) -> dict[str, object]:
    """生成一条因子输入。"""
    return {
        "symbol": symbol,
        "signal_date": "20200731",
        "cash_payout_y0": y0,
        "cash_payout_y1": y1,
        "cash_payout_y2": y2,
    }
