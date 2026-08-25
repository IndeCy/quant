"""Piotroski 财务 as-of 门面与覆盖门槛测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from data.piotroski_financial import (
    PiotroskiFinancialPaths,
    attach_piotroski_financial_databases,
    create_piotroski_signal_date_table,
    load_piotroski_financial_snapshot,
    materialize_piotroski_financial_asof,
)
from examples import piotroski_data_feasibility_study as study


def test_piotroski_snapshot_uses_visible_common_annual_reports(tmp_path: Path) -> None:
    """未来年报不可见，三张表共同披露后才能计算九项。"""
    paths = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_piotroski_signal_date_table(connection, ["20240429", "20240430"])
        attach_piotroski_financial_databases(connection, paths)
        materialize_piotroski_financial_asof(connection)
        snapshot = load_piotroski_financial_snapshot(connection)
    finally:
        connection.close()

    visible = snapshot[snapshot["f_score"].notna()]
    assert visible["signal_date"].tolist() == ["20240430"]
    assert visible.iloc[0]["report_period"] == "20231231"
    assert visible.iloc[0]["publish_date"] == "20240430"
    assert visible.iloc[0]["f_score"] == 9


def test_piotroski_feasibility_rejects_sparse_high_scores() -> None:
    """完整财务足够但高分股票过少时，不允许直接进入回测。"""
    dates = pd.date_range("2015-01-31", "2026-07-31", freq="ME")
    monthly = pd.DataFrame(
        {
            "signal_date": dates.strftime("%Y%m%d"),
            "complete_count": 500,
            "high_score_count": 5,
        }
    )

    result = study.evaluate_feasibility(monthly, {"8": 5}, "20260724")

    assert result["passed"] is False
    assert result["checks"]["complete_month_share"] is True
    assert result["checks"]["high_score_month_share"] is False


def _build_financial_databases(tmp_path: Path) -> PiotroskiFinancialPaths:
    """构造连续三年改善且 2023 年报在 2024-04-30 才可见的夹具。"""
    income = tmp_path / "income.duckdb"
    balance = tmp_path / "balance.duckdb"
    cashflow = tmp_path / "cashflow.duckdb"
    common_columns = (
        "ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR, "
        "f_ann_date VARCHAR, update_flag VARCHAR"
    )
    with duckdb.connect(str(income)) as connection:
        connection.execute(
            f"CREATE TABLE default_table({common_columns}, "
            "n_income_attr_p DOUBLE, revenue DOUBLE, oper_cost DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20211231", "20220401", "20220401", "1", 10, 100, 60),
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", 12, 110, 60),
                ("AAA.SZ", "20231231", "20240430", "20240430", "1", 15, 130, 65),
            ],
        )
    with duckdb.connect(str(balance)) as connection:
        connection.execute(
            f"CREATE TABLE default_table({common_columns}, "
            "total_assets DOUBLE, lt_borr DOUBLE, total_cur_assets DOUBLE, "
            "total_cur_liab DOUBLE, total_share DOUBLE, "
            "total_hldr_eqy_exc_min_int DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20211231", "20220401", "20220401", "1", 100, 30, 50, 30, 100, 60),
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", 105, 25, 60, 30, 100, 70),
                ("AAA.SZ", "20231231", "20240430", "20240430", "1", 110, 20, 70, 30, 100, 80),
            ],
        )
    with duckdb.connect(str(cashflow)) as connection:
        connection.execute(
            f"CREATE TABLE default_table({common_columns}, n_cashflow_act DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20211231", "20220401", "20220401", "1", 11),
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", 15),
                ("AAA.SZ", "20231231", "20240430", "20240430", "1", 20),
            ],
        )
    return PiotroskiFinancialPaths(income, balance, cashflow)
