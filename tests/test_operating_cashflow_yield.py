"""经营现金流收益率因子和 as-of 数据门面测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from data.operating_cashflow_yield import (
    OperatingCashflowYieldPaths,
    attach_operating_cashflow_yield_databases,
    create_operating_cashflow_yield_signal_dates,
    load_operating_cashflow_yield_snapshot,
    materialize_operating_cashflow_yield_asof,
)
from examples.operating_cashflow_yield_feasibility_study import (
    build_candidates,
)
from factors.operating_cashflow_yield import (
    score_operating_cashflow_yield,
)


def test_score_prefers_high_positive_cashflow_yield() -> None:
    """高正现金流收益率应优先，负现金流不得入选。"""
    frame = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW", "NEGATIVE"],
            "operating_cashflow_yield": [0.15, 0.03, -0.10],
        }
    )

    scored = score_operating_cashflow_yield(frame).set_index("symbol")

    assert set(scored.index) == {"HIGH", "LOW"}
    assert scored.loc["HIGH", "factor_score"] > scored.loc[
        "LOW",
        "factor_score",
    ]


def test_asof_snapshot_hides_future_and_uses_latest_visible_revision(
    tmp_path: Path,
) -> None:
    """信号日只能看到当时已披露的同年度现金流和总股本。"""
    paths = _build_statement_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_operating_cashflow_yield_signal_dates(
            connection,
            ["20230429", "20230430", "20240501"],
        )
        attach_operating_cashflow_yield_databases(connection, paths)
        materialize_operating_cashflow_yield_asof(connection)
        snapshot = load_operating_cashflow_yield_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["signal_date"].tolist() == ["20230430", "20240501"]
    assert snapshot["end_date"].tolist() == ["20221231", "20231231"]
    assert (snapshot["f_ann_date"] <= snapshot["signal_date"]).all()
    assert snapshot.iloc[0]["operating_cashflow"] == 100.0
    assert snapshot.iloc[1]["operating_cashflow"] == 250.0
    assert snapshot.iloc[1]["total_shares"] == 20.0


def test_candidate_formula_and_adjustment_gate() -> None:
    """市值分母必须使用同报告股本，重大公司行为必须剔除。"""
    base = {
        "signal_date": "20240131",
        "name": "正常公司",
        "list_date": "20100101",
        "delist_date": None,
        "st_name": None,
        "is_suspended": False,
        "end_date": "20221231",
        "f_ann_date": "20230331",
        "operating_cashflow": 200.0,
        "total_shares": 10.0,
        "raw_close": 5.0,
        "current_adj_factor": 1.0,
        "report_adj_factor": 1.0,
        "roa": 5.0,
        "earnings_yield": 0.08,
        "vol60": 0.2,
        "ret120": 0.1,
        "adv_rmb": 50_000_000.0,
        "amount": 100.0,
        "amount_p20": 20.0,
        "volume": 1000.0,
    }
    source = pd.DataFrame(
        [
            {**base, "symbol": "VALID"},
            {
                **base,
                "symbol": "ACTION",
                "current_adj_factor": 1.2,
            },
        ]
    )

    accepted, diagnostics = build_candidates(source)

    assert accepted["symbol"].tolist() == ["VALID"]
    assert accepted.iloc[0]["operating_cashflow_yield"] == 4.0
    assert diagnostics["material_action_share"] == 0.5


def _build_statement_databases(
    tmp_path: Path,
) -> OperatingCashflowYieldPaths:
    """创建含未来报告和修订记录的最小财务库。"""
    cashflow = tmp_path / "cashflow.duckdb"
    with duckdb.connect(str(cashflow)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                n_cashflow_act DOUBLE,
                update_flag VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20221231", "20230430", "20230430", 100.0, "1"),
                ("AAA.SZ", "20231231", "20240429", "20240429", 200.0, "0"),
                ("AAA.SZ", "20231231", "20240430", "20240430", 250.0, "1"),
            ],
        )
    balance = tmp_path / "balance.duckdb"
    with duckdb.connect(str(balance)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                total_share DOUBLE,
                update_flag VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20221231", "20230430", "20230430", 10.0, "1"),
                ("AAA.SZ", "20231231", "20240430", "20240430", 20.0, "1"),
            ],
        )
    return OperatingCashflowYieldPaths(cashflow, balance)
