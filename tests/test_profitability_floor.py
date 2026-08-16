"""五年盈利底线研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.profitability_history import (
    ProfitabilityHistoryPaths,
    attach_profitability_history_databases,
    create_profitability_signal_date_table,
    load_profitability_floor_snapshot,
    materialize_profitability_floor_asof,
)
from examples import profitability_floor_study as study
from factors.profitability_floor import score_profitability_floor_frame


def _create_profitability_databases(
    tmp_path: Path,
) -> ProfitabilityHistoryPaths:
    """创建六个连续年报及错开的信号日。"""
    indicator = tmp_path / "fina_indicator.duckdb"
    connection = duckdb.connect(str(indicator))
    connection.execute(
        "CREATE TABLE default_table(ts_code VARCHAR, end_date VARCHAR, roa DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO default_table VALUES (?, ?, ?)",
        [
            ("000001.SZ", f"{year}1231", float(year - 2014))
            for year in range(2015, 2022)
        ],
    )
    connection.close()

    statement_paths: list[Path] = []
    for filename in ["income.duckdb", "balancesheet.duckdb", "cashflow.duckdb"]:
        path = tmp_path / filename
        statement_paths.append(path)
        connection = duckdb.connect(str(path))
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                f_ann_date VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?)",
            [
                (
                    "000001.SZ",
                    f"{year}1231",
                    f"{year + 1}0430",
                )
                for year in range(2015, 2022)
            ],
        )
        connection.close()
    return ProfitabilityHistoryPaths(
        indicator=indicator,
        income=statement_paths[0],
        balance=statement_paths[1],
        cashflow=statement_paths[2],
    )


def test_profitability_floor_rolls_only_after_new_annual_report_is_visible(
    tmp_path: Path,
) -> None:
    """新年报披露前后应使用不同但连续的五年窗口。"""
    paths = _create_profitability_databases(tmp_path)
    connection = duckdb.connect()
    try:
        create_profitability_signal_date_table(
            connection,
            ["20210429", "20210531"],
        )
        attach_profitability_history_databases(connection, paths)
        materialize_profitability_floor_asof(connection)
        snapshot = load_profitability_floor_snapshot(connection)
    finally:
        connection.close()

    before = snapshot.set_index("signal_date").loc["20210429"]
    after = snapshot.set_index("signal_date").loc["20210531"]
    assert before["latest_fiscal_year"] == 2019
    assert before["roa_floor_5y"] == pytest.approx(1.0)
    assert after["latest_fiscal_year"] == 2020
    assert after["latest_publish_date"] == "20210430"
    assert after["roa_floor_5y"] == pytest.approx(2.0)
    assert after["current_roa"] == pytest.approx(6.0)


def test_profitability_floor_factor_requires_positive_five_year_floor() -> None:
    """五年中出现亏损的公司不能进入盈利韧性候选。"""
    frame = pd.DataFrame(
        {
            "symbol": ["RESILIENT", "LOSS", "SHORT"],
            "roa_floor_5y": [5.0, -1.0, 8.0],
            "observations": [5, 5, 4],
        }
    )

    result = score_profitability_floor_frame(frame)

    assert result["symbol"].tolist() == ["RESILIENT"]


def test_profitability_floor_factor_prefers_higher_worst_year_roa() -> None:
    """最差年份ROA更高的公司应获得更高分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW"],
            "roa_floor_5y": [8.0, 2.0],
            "observations": [5, 5],
        }
    )

    result = score_profitability_floor_frame(frame).set_index("symbol")

    assert result.loc["HIGH", "factor_score"] > result.loc["LOW", "factor_score"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同财务版本和研究定义不得重复回测。"""
    for name in [
        "fina_indicator.duckdb",
        "income.duckdb",
        "balancesheet.duckdb",
        "cashflow.duckdb",
    ]:
        (tmp_path / name).write_bytes(b"test")

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
