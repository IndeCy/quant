"""年度 ROA 改善点时门面、评分与研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.profitability_improvement import (
    ProfitabilityImprovementPaths,
    attach_profitability_improvement_databases,
    create_profitability_improvement_signal_dates,
    load_profitability_improvement_snapshot,
    materialize_profitability_improvement_asof,
)
from examples import profitability_improvement_feasibility_study as study
from examples import profitability_improvement_study as strategy_study
from factors.profitability_improvement import score_profitability_improvement


def test_asof_waits_for_both_new_annual_statements(tmp_path: Path) -> None:
    """新利润表和资产负债表没有同时披露时不得看到新 ROA。"""
    income, balance = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_profitability_improvement_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_profitability_improvement_databases(
            connection,
            ProfitabilityImprovementPaths(income, balance),
        )
        materialize_profitability_improvement_asof(connection)
        frame = load_profitability_improvement_snapshot(connection)
    finally:
        connection.close()

    assert frame["report_period"].tolist() == ["20221231", "20231231"]
    assert frame["publish_date"].tolist() == ["20230331", "20240430"]
    assert frame["roa_change"].tolist() == pytest.approx([0.03, 0.05])


def test_score_prefers_larger_roa_improvement() -> None:
    """ROA 改善更大的公司必须获得更高分。"""
    scored = score_profitability_improvement(
        pd.DataFrame(
            {
                "symbol": ["IMPROVING", "DETERIORATING"],
                "roa_change": [0.05, -0.03],
            }
        )
    ).set_index("symbol")

    assert scored.loc["IMPROVING", "factor_score"] > scored.loc[
        "DETERIORATING",
        "factor_score",
    ]


def test_feasibility_reuses_same_fingerprint_without_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义和数据版本必须在扫描财务库前直接复用。"""
    for path in [
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]:
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
        lambda *args, **kwargs: pytest.fail("不应重新扫描"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_strategy_definition_uses_grid_risk_overlay() -> None:
    """正式回测必须显式启用冻结风险层。"""
    assert strategy_study.RESEARCH_SPEC.definition["risk_overlay"] == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }


def test_strategy_reuses_same_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同策略指纹必须在回测前复用历史结果。"""
    for path in [
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
        tmp_path / "data" / "benchmark_increment.duckdb",
    ]:
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


def _build_financial_databases(tmp_path: Path) -> tuple[Path, Path]:
    """构造四年连续年报，2023年两张报表披露日不同。"""
    income = tmp_path / "income.duckdb"
    balance = tmp_path / "balancesheet.duckdb"
    with duckdb.connect(str(income)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR,
                f_ann_date VARCHAR, report_type VARCHAR, comp_type VARCHAR,
                n_income_attr_p DOUBLE, update_flag VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?,?,?,?,?,?,?,?)",
            [
                ("AAA.SZ", "20201231", "20210331", "20210331", "1", "1", 5.0, "1"),
                ("AAA.SZ", "20211231", "20220331", "20220331", "1", "1", 7.0, "1"),
                ("AAA.SZ", "20221231", "20230331", "20230331", "1", "1", 10.0, "1"),
                ("AAA.SZ", "20231231", "20240429", "20240429", "1", "1", 15.0, "1"),
            ],
        )
    with duckdb.connect(str(balance)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR,
                f_ann_date VARCHAR, report_type VARCHAR, comp_type VARCHAR,
                total_assets DOUBLE, update_flag VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?,?,?,?,?,?,?,?)",
            [
                ("AAA.SZ", "20201231", "20210331", "20210331", "1", "1", 100.0, "1"),
                ("AAA.SZ", "20211231", "20220331", "20220331", "1", "1", 100.0, "1"),
                ("AAA.SZ", "20221231", "20230331", "20230331", "1", "1", 100.0, "1"),
                ("AAA.SZ", "20231231", "20240430", "20240430", "1", "1", 100.0, "1"),
            ],
        )
    return income, balance
