"""净债务融资点时门面和可行性门槛测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.net_debt_financing import (
    NetDebtFinancingPaths,
    attach_net_debt_financing_databases,
    create_net_debt_financing_signal_dates,
    load_net_debt_financing_snapshot,
    materialize_net_debt_financing_asof,
)
from examples import net_debt_financing_feasibility_study as study
from examples import net_debt_financing_study as strategy_study
from factors.net_debt_financing import score_net_debt_financing_frame


def test_snapshot_waits_until_both_statements_are_visible(
    tmp_path: Path,
) -> None:
    """同年资产负债表未披露前不得提前使用现金流量表。"""
    cashflow, balance = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_net_debt_financing_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_net_debt_financing_databases(
            connection,
            NetDebtFinancingPaths(cashflow, balance),
        )
        materialize_net_debt_financing_asof(connection)
        snapshot = load_net_debt_financing_snapshot(connection)
    finally:
        connection.close()

    before = snapshot[snapshot["signal_date"].eq("20240429")].iloc[0]
    after = snapshot[snapshot["signal_date"].eq("20240430")].iloc[0]
    assert before["report_period"] == "20221231"
    assert after["report_period"] == "20231231"
    assert after["publish_date"] == "20240430"
    assert float(after["net_debt_financing"]) == pytest.approx(-0.15)


def test_missing_components_are_zero_but_auditable(tmp_path: Path) -> None:
    """无债务活动字段可按零处理，但必须保留全缺失标记。"""
    cashflow, balance = _build_financial_databases(
        tmp_path,
        latest_components=(None, None, None),
    )
    connection = duckdb.connect(":memory:")
    try:
        create_net_debt_financing_signal_dates(connection, ["20240430"])
        attach_net_debt_financing_databases(
            connection,
            NetDebtFinancingPaths(cashflow, balance),
        )
        materialize_net_debt_financing_asof(connection)
        row = load_net_debt_financing_snapshot(connection).iloc[0]
    finally:
        connection.close()

    assert bool(row["all_debt_cashflow_missing"]) is True
    assert float(row["net_debt_financing"]) == 0.0


def test_feasibility_rejects_high_all_component_missingness() -> None:
    """无法区分零活动与缺数时不得进入回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131"],
            "candidate_count": [800, 900],
            "negative_candidate_count": [100, 120],
        }
    )
    diagnostics = {
        "visibility_violations": 0.0,
        "duplicate_signal_symbol_rows": 0.0,
        "borrowing_cash_missing_share": 0.4,
        "bond_issue_cash_missing_share": 0.8,
        "debt_repayment_cash_missing_share": 0.4,
        "all_components_missing_share": 0.3,
    }
    distribution = {
        "p01": -0.2,
        "median": 0.0,
        "p99": 0.3,
        "zero_share": 0.2,
    }

    result = study.evaluate_feasibility(
        monthly,
        distribution,
        diagnostics,
        "20220131",
    )

    assert result["passed"] is False
    assert result["checks"]["all_components_missing_within_limit"] is False


def test_feasibility_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同研究指纹必须复用，不重复扫描两张财务大表。"""
    files = [
        tmp_path / "cashflow.duckdb",
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


def test_factor_prefers_net_debt_repayment() -> None:
    """净偿债公司必须比净融资公司获得更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["REPAY", "BORROW", "INVALID"],
            "net_debt_financing": [-0.15, 0.20, float("inf")],
        }
    )

    scored = score_net_debt_financing_frame(frame).set_index("symbol")

    assert set(scored.index) == {"REPAY", "BORROW"}
    assert scored.loc["REPAY", "factor_score"] > scored.loc["BORROW", "factor_score"]


def test_duckdb_name_filter_matches_st_substring() -> None:
    """ST标记位于名称中间时也必须被正则识别。"""
    with duckdb.connect(":memory:") as connection:
        matched = connection.execute(
            "SELECT REGEXP_MATCHES('*ST起步', 'ST|退')"
        ).fetchone()[0]

    assert matched is True


def test_strategy_reuses_same_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """正式策略相同指纹必须复用，禁止重复M0回测。"""
    files = [
        tmp_path / "cashflow.duckdb",
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


def test_latest_holdings_serialize_missing_financial_fields_as_null() -> None:
    """未发行债券等财务空值必须归档为null而不是NaN。"""
    frame = pd.DataFrame(
        {
            "symbol": ["AAA.SZ"],
            "bond_issue_cash": [float("nan")],
        }
    )

    records = strategy_study.records_without_missing(frame)

    assert records == [{"symbol": "AAA.SZ", "bond_issue_cash": None}]


def _build_financial_databases(
    tmp_path: Path,
    *,
    latest_components: tuple[float | None, float | None, float | None] = (
        20.0,
        10.0,
        60.0,
    ),
) -> tuple[Path, Path]:
    """构造两年一般工商业现金流和资产负债表。"""
    cashflow = tmp_path / "cashflow.duckdb"
    balance = tmp_path / "balancesheet.duckdb"
    with duckdb.connect(str(cashflow)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                update_flag VARCHAR,
                report_type VARCHAR,
                comp_type VARCHAR,
                c_recp_borrow DOUBLE,
                proc_issue_bonds DOUBLE,
                c_prepay_amt_borr DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "AAA.SZ", "20221231", "20230401", "20230401", "1", "1", "1",
                    30.0, 0.0, 20.0,
                ),
                (
                    "AAA.SZ", "20231231", "20240420", "20240420", "1", "1", "1",
                    *latest_components,
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
                report_type VARCHAR,
                comp_type VARCHAR,
                total_assets DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "AAA.SZ", "20221231", "20230401", "20230401",
                    "1", "1", "1", 100.0,
                ),
                (
                    "AAA.SZ", "20231231", "20240430", "20240430",
                    "1", "1", "1", 200.0,
                ),
            ],
        )
    return cashflow, balance
