"""资产周转率改善 as-of 门面和研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.asset_turnover_change import (
    AssetTurnoverFinancialPaths,
    attach_asset_turnover_databases,
    create_asset_turnover_signal_dates,
    load_asset_turnover_change_snapshot,
    materialize_asset_turnover_change_asof,
)
from examples import asset_turnover_change_feasibility_study as study
from examples import asset_turnover_change_study as strategy_study
from factors.asset_turnover_change import score_asset_turnover_change_frame


def test_snapshot_switches_only_after_both_new_reports_are_visible(
    tmp_path: Path,
) -> None:
    """利润表和资产负债表均披露后才能切换到新年报。"""
    income, balance = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_asset_turnover_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_asset_turnover_databases(
            connection,
            AssetTurnoverFinancialPaths(income, balance),
        )
        materialize_asset_turnover_change_asof(connection)
        snapshot = load_asset_turnover_change_snapshot(connection)
    finally:
        connection.close()

    before = snapshot[snapshot["signal_date"].eq("20240429")].iloc[0]
    after = snapshot[snapshot["signal_date"].eq("20240430")].iloc[0]
    assert before["report_period"] == "20221231"
    assert before["asset_turnover"] == pytest.approx(120 / 135)
    assert before["prior_asset_turnover"] == pytest.approx(100 / 110)
    assert before["asset_turnover_change"] == pytest.approx(120 / 135 - 100 / 110)
    assert after["report_period"] == "20231231"
    assert after["publish_date"] == "20240430"
    assert after["asset_turnover_change"] == pytest.approx(180 / 165 - 120 / 135)


def test_snapshot_uses_visible_revision_not_future_restatement(
    tmp_path: Path,
) -> None:
    """信号日之后发布的修订值不得覆盖当时可见年报。"""
    income, balance = _build_financial_databases(tmp_path, add_future_revision=True)
    connection = duckdb.connect(":memory:")
    try:
        create_asset_turnover_signal_dates(connection, ["20240430"])
        attach_asset_turnover_databases(
            connection,
            AssetTurnoverFinancialPaths(income, balance),
        )
        materialize_asset_turnover_change_asof(connection)
        snapshot = load_asset_turnover_change_snapshot(connection)
    finally:
        connection.close()

    assert snapshot.iloc[0]["revenue"] == pytest.approx(180)
    assert snapshot.iloc[0]["publish_date"] == "20240430"


def test_feasibility_rejects_sparse_or_degenerate_months() -> None:
    """覆盖不足或唯一值过少时不得进入正式回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131", "20220228"],
            "candidate_count": [600, 100, 600],
            "unique_factor_values": [500, 50, 500],
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {
            "change_p01": -0.2,
            "change_median": 0.0,
            "change_p99": 0.2,
            "level_p01": 0.1,
            "level_median": 0.8,
            "level_p99": 2.0,
        },
        {
            "visibility_violations": 0,
            "duplicate_signal_symbol_rows": 0,
            "median_spearman_with_turnover_level": 0.1,
        },
        "20220228",
    )

    assert result["passed"] is False
    assert result["checks"]["locked_candidate_month_share"] is False
    assert result["checks"]["locked_unique_value_month_share"] is False


def test_factor_prefers_larger_turnover_improvement() -> None:
    """周转效率改善更大的公司必须获得更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["IMPROVING", "FLAT", "INVALID"],
            "asset_turnover_change": [0.2, 0.0, float("inf")],
        }
    )
    scored = score_asset_turnover_change_frame(frame).set_index("symbol")

    assert set(scored.index) == {"IMPROVING", "FLAT"}
    assert scored.loc["IMPROVING", "factor_score"] > scored.loc["FLAT", "factor_score"]


def test_feasibility_reuses_same_fingerprint_without_data_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同口径和数据版本必须复用，禁止重复读取大表。"""
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
    """正式策略相同运行指纹不得再次启动回测。"""
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
    add_future_revision: bool = False,
) -> tuple[Path, Path]:
    """构造四年年报，2023年两表在不同日期完成披露。"""
    income = tmp_path / "income.duckdb"
    balance = tmp_path / "balancesheet.duckdb"
    income_rows = [
        ("AAA.SZ", "20201231", "20210401", "20210401", "1", "1", "1", 80),
        ("AAA.SZ", "20211231", "20220401", "20220401", "1", "1", "1", 100),
        ("AAA.SZ", "20221231", "20230401", "20230401", "1", "1", "1", 120),
        ("AAA.SZ", "20231231", "20240430", "20240430", "1", "1", "1", 180),
    ]
    if add_future_revision:
        income_rows.append(
            ("AAA.SZ", "20231231", "20240502", "20240502", "1", "1", "1", 999)
        )
    with duckdb.connect(str(income)) as connection:
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
                revenue DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            income_rows,
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
                ("AAA.SZ", "20201231", "20210401", "20210401", "1", "1", "1", 100),
                ("AAA.SZ", "20211231", "20220401", "20220401", "1", "1", "1", 120),
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", "1", "1", 150),
                ("AAA.SZ", "20231231", "20240429", "20240429", "1", "1", "1", 180),
            ],
        )
    return income, balance
