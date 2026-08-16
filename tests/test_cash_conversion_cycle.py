"""现金转换周期 as-of 门面和研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.cash_conversion_cycle import (
    CashConversionFinancialPaths,
    attach_cash_conversion_databases,
    create_cash_conversion_signal_dates,
    load_cash_conversion_cycle_snapshot,
    materialize_cash_conversion_cycle_asof,
)
from examples import cash_conversion_cycle_feasibility_study as study
from examples import cash_conversion_cycle_study as strategy_study
from factors.cash_conversion_cycle import score_cash_conversion_cycle_frame


def test_snapshot_switches_only_after_both_reports_are_visible(
    tmp_path: Path,
) -> None:
    """利润表和资产负债表均可见后才能使用新年度周期。"""
    income, balance = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_cash_conversion_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_cash_conversion_databases(
            connection,
            CashConversionFinancialPaths(income, balance),
        )
        materialize_cash_conversion_cycle_asof(connection)
        snapshot = load_cash_conversion_cycle_snapshot(connection)
    finally:
        connection.close()

    before = snapshot[snapshot["signal_date"].eq("20240429")].iloc[0]
    after = snapshot[snapshot["signal_date"].eq("20240430")].iloc[0]
    assert before["report_period"] == "20221231"
    assert after["report_period"] == "20231231"
    assert after["publish_date"] == "20240430"
    assert after["receivable_days"] == pytest.approx(365 * 22 / 180)
    assert after["inventory_days"] == pytest.approx(365 * 32 / 100)
    assert after["payable_days"] == pytest.approx(365 * 17 / 100)
    expected = (365 * 22 / 180 + 365 * 32 / 100 - 365 * 17 / 100) - (
        365 * 17 / 140 + 365 * 27 / 80 - 365 * 14 / 80
    )
    assert after["cash_conversion_cycle_change"] == pytest.approx(expected)


def test_missing_component_remains_missing_instead_of_zero(
    tmp_path: Path,
) -> None:
    """应付账款缺失时周期必须为空，禁止把缺失当作零天。"""
    income, balance = _build_financial_databases(
        tmp_path,
        missing_latest_payable=True,
    )
    connection = duckdb.connect(":memory:")
    try:
        create_cash_conversion_signal_dates(connection, ["20240430"])
        attach_cash_conversion_databases(
            connection,
            CashConversionFinancialPaths(income, balance),
        )
        materialize_cash_conversion_cycle_asof(connection)
        snapshot = load_cash_conversion_cycle_snapshot(connection)
    finally:
        connection.close()

    row = snapshot.iloc[0]
    assert bool(row["required_component_missing"]) is True
    assert pd.isna(row["cash_conversion_cycle"])
    assert pd.isna(row["cash_conversion_cycle_change"])


def test_future_revision_does_not_replace_visible_statement(
    tmp_path: Path,
) -> None:
    """信号日后的利润表修订不得进入当期周期计算。"""
    income, balance = _build_financial_databases(
        tmp_path,
        add_future_revision=True,
    )
    connection = duckdb.connect(":memory:")
    try:
        create_cash_conversion_signal_dates(connection, ["20240430"])
        attach_cash_conversion_databases(
            connection,
            CashConversionFinancialPaths(income, balance),
        )
        materialize_cash_conversion_cycle_asof(connection)
        snapshot = load_cash_conversion_cycle_snapshot(connection)
    finally:
        connection.close()

    assert snapshot.iloc[0]["revenue"] == pytest.approx(180)
    assert snapshot.iloc[0]["operating_cost"] == pytest.approx(100)


def test_factor_prefers_larger_cycle_reduction() -> None:
    """周期缩短幅度更大的公司必须获得更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["BETTER", "FLAT", "WORSE", "INVALID"],
            "cash_conversion_cycle_change": [-30.0, 0.0, 20.0, float("inf")],
        }
    )
    scored = score_cash_conversion_cycle_frame(frame).set_index("symbol")

    assert set(scored.index) == {"BETTER", "FLAT", "WORSE"}
    assert scored.loc["BETTER", "factor_score"] > scored.loc["WORSE", "factor_score"]


def test_feasibility_rejects_low_complete_coverage() -> None:
    """完整财务字段覆盖不足时不得进入回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131", "20220228"],
            "investable_count": [2000, 2000, 2000],
            "candidate_count": [1200, 300, 1200],
            "coverage": [0.60, 0.15, 0.60],
            "unique_factor_values": [1200, 300, 1200],
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {
            "change_p01": -100.0,
            "change_median": 0.0,
            "change_p99": 100.0,
            "level_p01": -10.0,
            "level_median": 80.0,
            "level_p99": 500.0,
        },
        {
            "visibility_violations": 0,
            "duplicate_signal_symbol_rows": 0,
            "financial_snapshot_missing_share": 0.1,
            "required_component_missing_share": 0.4,
        },
        "20220228",
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_feasibility_reuses_same_fingerprint_without_data_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同运行指纹必须复用，禁止再次扫描财务大表。"""
    files = [
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

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
        lambda *args, **kwargs: pytest.fail("不应读取财务大表"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_strategy_reuses_same_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """正式策略相同运行指纹不得重复回测。"""
    files = [
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": strategy_study.STRATEGY_ID}

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


def _build_financial_databases(
    tmp_path: Path,
    *,
    missing_latest_payable: bool = False,
    add_future_revision: bool = False,
) -> tuple[Path, Path]:
    """构造四年连续年报及不同披露日期。"""
    income = tmp_path / "income.duckdb"
    balance = tmp_path / "balancesheet.duckdb"
    income_rows = [
        ("AAA.SZ", "20201231", "20210401", "20210401", "1", "1", "1", 100, 60),
        ("AAA.SZ", "20211231", "20220401", "20220401", "1", "1", "1", 120, 70),
        ("AAA.SZ", "20221231", "20230401", "20230401", "1", "1", "1", 140, 80),
        ("AAA.SZ", "20231231", "20240430", "20240430", "1", "1", "1", 180, 100),
    ]
    if add_future_revision:
        income_rows.append(
            ("AAA.SZ", "20231231", "20240502", "20240502", "1", "1", "1", 999, 999)
        )
    with duckdb.connect(str(income)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR,
                f_ann_date VARCHAR, update_flag VARCHAR, report_type VARCHAR,
                comp_type VARCHAR, revenue DOUBLE, oper_cost DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            income_rows,
        )
    with duckdb.connect(str(balance)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR,
                f_ann_date VARCHAR, update_flag VARCHAR, report_type VARCHAR,
                comp_type VARCHAR, accounts_receiv DOUBLE,
                inventories DOUBLE, acct_payable DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20201231", "20210401", "20210401", "1", "1", "1", 10, 20, 10),
                ("AAA.SZ", "20211231", "20220401", "20220401", "1", "1", "1", 14, 24, 12),
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", "1", "1", 20, 30, 16),
                (
                    "AAA.SZ",
                    "20231231",
                    "20240429",
                    "20240429",
                    "1",
                    "1",
                    "1",
                    24,
                    34,
                    None if missing_latest_payable else 18,
                ),
            ],
        )
    return income, balance
