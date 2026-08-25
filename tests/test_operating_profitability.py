"""经营盈利能力点时数据和可行性门槛测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.operating_profitability import (
    OperatingProfitabilityPaths,
    attach_operating_profitability_databases,
    create_operating_profitability_signal_dates,
    load_operating_profitability_snapshot,
    materialize_operating_profitability_asof,
)
from examples import operating_profitability_feasibility_study as study
from examples import operating_profitability_study as strategy_study
from factors.operating_profitability import score_operating_profitability_frame


def test_snapshot_uses_only_statements_visible_on_signal_date(
    tmp_path: Path,
) -> None:
    """资产负债表未披露时不能提前使用同年利润表。"""
    income, balance = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_operating_profitability_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_operating_profitability_databases(
            connection,
            OperatingProfitabilityPaths(income, balance),
        )
        materialize_operating_profitability_asof(connection)
        snapshot = load_operating_profitability_snapshot(connection)
    finally:
        connection.close()

    before = snapshot[snapshot["signal_date"].eq("20240429")].iloc[0]
    after = snapshot[snapshot["signal_date"].eq("20240430")].iloc[0]
    assert before["report_period"] == "20221231"
    assert after["report_period"] == "20231231"
    assert after["publish_date"] == "20240430"
    assert float(after["operating_profitability"]) == pytest.approx(0.30)


def test_missing_optional_expenses_are_zero_but_auditable(
    tmp_path: Path,
) -> None:
    """可选费用缺失按零计算，同时必须保留缺失标记。"""
    income, balance = _build_financial_databases(tmp_path, missing_expenses=True)
    connection = duckdb.connect(":memory:")
    try:
        create_operating_profitability_signal_dates(connection, ["20240430"])
        attach_operating_profitability_databases(
            connection,
            OperatingProfitabilityPaths(income, balance),
        )
        materialize_operating_profitability_asof(connection)
        row = load_operating_profitability_snapshot(connection).iloc[0]
    finally:
        connection.close()

    assert bool(row["selling_expense_missing"]) is True
    assert bool(row["admin_expense_missing"]) is True
    assert bool(row["interest_expense_missing"]) is True
    assert float(row["operating_profitability"]) == pytest.approx(0.50)


def test_feasibility_rejects_high_component_missingness() -> None:
    """费用字段大面积缺失时不得把粗糙代理送入回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131"],
            "candidate_count": [800, 900],
        }
    )
    diagnostics = {
        "visibility_violations": 0.0,
        "duplicate_signal_symbol_rows": 0.0,
        "selling_expense_missing_share": 0.10,
        "admin_expense_missing_share": 0.10,
        "interest_expense_missing_share": 0.80,
        "latest_p01": -0.2,
        "latest_median": 0.1,
        "latest_p99": 0.8,
    }

    result = study.evaluate_feasibility(monthly, diagnostics, "20220131")

    assert result["passed"] is False
    assert result["checks"]["interest_expense_missing_within_limit"] is False


def test_feasibility_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同数据与定义必须命中历史结果，不能重复扫描财务库。"""
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
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260725")

    assert result["reused"] is True


def test_factor_prefers_higher_operating_profitability() -> None:
    """经营盈利能力越高必须得到更高横截面分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["ROBUST", "WEAK", "INVALID"],
            "operating_profitability": [0.30, -0.10, float("inf")],
        }
    )

    scored = score_operating_profitability_frame(frame).set_index("symbol")

    assert set(scored.index) == {"ROBUST", "WEAK"}
    assert scored.loc["ROBUST", "factor_score"] > scored.loc["WEAK", "factor_score"]


def test_strategy_reuses_same_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同正式策略指纹必须复用历史结果，禁止重复回测。"""
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
        "20260725",
    )

    assert result["reused"] is True


def _build_financial_databases(
    tmp_path: Path,
    *,
    missing_expenses: bool = False,
) -> tuple[Path, Path]:
    """构造公告日不同步的连续年度利润表和资产负债表。"""
    income = tmp_path / "income.duckdb"
    balance = tmp_path / "balancesheet.duckdb"
    with duckdb.connect(str(income)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                update_flag VARCHAR,
                revenue DOUBLE,
                oper_cost DOUBLE,
                sell_exp DOUBLE,
                admin_exp DOUBLE,
                fin_exp_int_exp DOUBLE,
                int_exp DOUBLE
            )
            """
        )
        optional = (None, None, None) if missing_expenses else (10.0, 5.0, 5.0)
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "AAA.SZ", "20221231", "20230401", "20230401", "1",
                    100.0, 60.0, optional[0], optional[1], optional[2], None,
                ),
                (
                    "AAA.SZ", "20231231", "20240420", "20240420", "1",
                    120.0, 70.0, optional[0], optional[1], optional[2], None,
                ),
            ],
        )
    with duckdb.connect(str(balance)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                update_flag VARCHAR,
                total_hldr_eqy_inc_min_int DOUBLE,
                total_assets DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", 50.0, 100.0),
                ("AAA.SZ", "20231231", "20240430", "20240430", "1", 100.0, 200.0),
            ],
        )
    return income, balance
