"""毛利率变化 as-of 门面与可行性门槛测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.gross_margin_change import (
    GrossMarginFinancialPaths,
    attach_gross_margin_financial_database,
    create_gross_margin_signal_date_table,
    load_gross_margin_change_snapshot,
    materialize_gross_margin_change_asof,
)
from examples import gross_margin_expansion_feasibility_study as study
from examples import gross_margin_expansion_study as strategy_study
from examples import gross_margin_expansion_v2_study as v2_strategy_study
from factors.gross_margin_expansion import score_gross_margin_expansion_frame
from factors.gross_margin_expansion import (
    score_gross_margin_expansion_rank_frame,
)


def test_snapshot_switches_only_after_new_annual_report_is_visible(
    tmp_path: Path,
) -> None:
    """新年报公告日前只能使用旧的连续年度组合。"""
    income = _build_income_database(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_gross_margin_signal_date_table(
            connection,
            ["20240429", "20240430"],
        )
        attach_gross_margin_financial_database(
            connection,
            GrossMarginFinancialPaths(income),
        )
        materialize_gross_margin_change_asof(connection)
        snapshot = load_gross_margin_change_snapshot(connection)
    finally:
        connection.close()

    before = snapshot[snapshot["signal_date"].eq("20240429")].iloc[0]
    after = snapshot[snapshot["signal_date"].eq("20240430")].iloc[0]
    assert before["report_period"] == "20221231"
    assert before["gross_margin_change"] == pytest.approx(0.1)
    assert after["report_period"] == "20231231"
    assert after["publish_date"] == "20240430"
    assert round(float(after["gross_margin_change"]), 8) == -0.05


def test_feasibility_rejects_sparse_months() -> None:
    """多数月份候选不足时不得进入回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131", "20220228"],
            "candidate_count": [100, 100, 800],
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {"p01": -0.1, "median": 0.0, "p99": 0.1},
        0,
        "20220228",
    )

    assert result["passed"] is False
    assert result["checks"]["full_candidate_month_share"] is False


def test_factor_prefers_larger_gross_margin_expansion() -> None:
    """毛利率改善幅度更大的公司必须获得更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["IMPROVING", "FLAT", "INVALID"],
            "gross_margin_change": [0.08, 0.0, float("inf")],
        }
    )
    scored = score_gross_margin_expansion_frame(frame).set_index("symbol")

    assert set(scored.index) == {"IMPROVING", "FLAT"}
    assert scored.loc["IMPROVING", "factor_score"] > scored.loc["FLAT", "factor_score"]


def test_v2_raw_rank_keeps_extreme_values_ordered() -> None:
    """V2不得把横截面顶部1%的不同改善幅度压成相同分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "gross_margin_change": [0.50, 0.40, 0.10, 0.0],
        }
    )
    scored = score_gross_margin_expansion_rank_frame(frame).set_index("symbol")

    assert scored.loc["A", "factor_score"] > scored.loc["B", "factor_score"]


def test_strategy_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同正式策略定义和数据版本不能重复回测。"""
    files = [
        tmp_path / "income.duckdb",
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
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = strategy_study.run_study(
        strategy_study.RuntimePaths(tmp_path),
        "20260725",
    )

    assert result["reused"] is True


def test_v2_strategy_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V2语义修正版也必须复用确定性指纹，禁止重复试验。"""
    files = [
        tmp_path / "income.duckdb",
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": v2_strategy_study.STRATEGY_ID}

    monkeypatch.setattr(
        v2_strategy_study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        v2_strategy_study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = v2_strategy_study.run_study(
        v2_strategy_study.RuntimePaths(tmp_path),
        "20260725",
    )

    assert result["reused"] is True


def _build_income_database(tmp_path: Path) -> Path:
    """构造三份连续年报，2023年报在2024-04-30可见。"""
    path = tmp_path / "income.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                update_flag VARCHAR,
                revenue DOUBLE,
                oper_cost DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20211231", "20220401", "20220401", "1", 100, 60),
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", 100, 50),
                ("AAA.SZ", "20231231", "20240430", "20240430", "1", 100, 55),
            ],
        )
    return path
