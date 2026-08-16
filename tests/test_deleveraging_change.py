"""年度去杠杆变化点时门面与评分测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.deleveraging_change import (
    DeleveragingPaths,
    attach_deleveraging_database,
    create_deleveraging_signal_dates,
    load_deleveraging_change_snapshot,
    materialize_deleveraging_change_asof,
)
from factors.deleveraging_change import score_deleveraging_change
from examples import deleveraging_change_study as strategy_study


def test_asof_waits_for_new_annual_balance_sheet(tmp_path: Path) -> None:
    """新年报披露前不得提前看到当年去杠杆变化。"""
    balance = tmp_path / "balancesheet.duckdb"
    _build_balance_database(balance)
    connection = duckdb.connect(":memory:")
    try:
        create_deleveraging_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_deleveraging_database(connection, DeleveragingPaths(balance))
        materialize_deleveraging_change_asof(connection)
        frame = load_deleveraging_change_snapshot(connection)
    finally:
        connection.close()

    assert frame["report_period"].tolist() == ["20221231", "20231231"]
    assert frame["debt_to_assets_change"].tolist() == pytest.approx(
        [-0.1, -0.1]
    )


def test_score_prefers_larger_deleveraging() -> None:
    """负债率下降更多的公司必须得分更高。"""
    scored = score_deleveraging_change(
        pd.DataFrame(
            {
                "symbol": ["DOWN", "UP"],
                "debt_to_assets_change": [-0.1, 0.1],
            }
        )
    ).set_index("symbol")

    assert scored.loc["DOWN", "factor_score"] > scored.loc[
        "UP",
        "factor_score",
    ]


def test_strategy_definition_uses_grid_risk_overlay() -> None:
    """正式回测必须显式启用冻结风险层。"""
    assert strategy_study.RESEARCH_SPEC.definition["risk_overlay"] == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }


def _build_balance_database(path: Path) -> None:
    """构造三份连续年报资产负债表。"""
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR,
                f_ann_date VARCHAR, report_type VARCHAR, comp_type VARCHAR,
                total_assets DOUBLE, total_liab DOUBLE, update_flag VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    "AAA.SZ", "20211231", "20220331", "20220331",
                    "1", "1", 100.0, 60.0, "1",
                ),
                (
                    "AAA.SZ", "20221231", "20230331", "20230331",
                    "1", "1", 100.0, 50.0, "1",
                ),
                (
                    "AAA.SZ", "20231231", "20240430", "20240430",
                    "1", "1", 100.0, 40.0, "1",
                ),
            ],
        )
