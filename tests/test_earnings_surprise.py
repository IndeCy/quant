"""标准化意外盈利数据门面与因子测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from data.earnings_surprise import (
    EarningsSurprisePaths,
    attach_earnings_surprise_database,
    create_earnings_surprise_signal_date_table,
    load_earnings_surprise_snapshot,
    materialize_earnings_surprise_asof,
)
from examples import earnings_surprise_data_feasibility_study as study
from factors.earnings_surprise import (
    score_earnings_surprise_frame,
    score_earnings_surprise_rank_frame,
)


def test_sue_asof_uses_only_previously_announced_history(
    tmp_path: Path,
) -> None:
    """当前公告不得进入自己的8期历史标准差。"""
    income_path = tmp_path / "income.duckdb"
    rows = _quarterly_rows()
    with duckdb.connect(str(income_path)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                f_ann_date VARCHAR,
                basic_eps DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?)",
            rows,
        )
    connection = duckdb.connect()
    try:
        attach_earnings_surprise_database(
            connection,
            EarningsSurprisePaths(income_path),
        )
        create_earnings_surprise_signal_date_table(
            connection,
            ["20201231", "20210430"],
        )
        materialize_earnings_surprise_asof(connection)
        result = load_earnings_surprise_snapshot(connection)
    finally:
        connection.close()

    assert not result.empty
    assert (result["publish_date"] <= result["signal_date"]).all()
    assert (result["history_observations"] == 8).all()
    late = result[result["signal_date"] == "20210430"].iloc[0]
    assert late["end_date"] == "20201231"


def test_sue_factor_requires_positive_surprise() -> None:
    """亏损或负意外盈利不能进入正向SUE候选池。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "signal_date": ["20240131"] * 3,
            "basic_eps": [1.0, -1.0, 1.0],
            "eps_change": [0.2, 0.3, -0.1],
            "historical_change_std": [0.1, 0.1, 0.1],
            "history_observations": [8, 8, 8],
            "sue": [2.0, 3.0, -1.0],
            "event_age_days": [10, 10, 10],
        }
    )

    result = score_earnings_surprise_frame(frame)

    assert result["symbol"].tolist() == ["A"]
    assert result.iloc[0]["factor_score"] == 1.0


def test_raw_sue_rank_does_not_tie_extreme_tail() -> None:
    """V2原始秩必须保留极端SUE之间的顺序。"""
    frame = pd.DataFrame(
        {
            "symbol": [str(index) for index in range(200)],
            "signal_date": ["20240131"] * 200,
            "basic_eps": [1.0] * 200,
            "eps_change": [float(index + 1) for index in range(200)],
            "historical_change_std": [1.0] * 200,
            "history_observations": [8] * 200,
            "sue": [float(index + 1) for index in range(200)],
            "event_age_days": [10] * 200,
        }
    )

    result = score_earnings_surprise_rank_frame(frame).head(3)

    assert result["symbol"].tolist() == ["199", "198", "197"]
    assert result["factor_score"].nunique() == 3


def test_feasibility_gate_rejects_missing_months() -> None:
    """任何月份无法构造Top20时不得启动回测。"""
    diagnostics = {
        "asof_violations": 0,
        "event_age_violations": 0,
        "history_observation_violations": 0,
        "duplicate_signal_symbol": 0,
        "constructible_month_share": 0.99,
        "candidate_count_median": 200,
        "candidate_count_latest": 200,
        "fold_constructible_share": {"a": 1.0, "b": 1.0},
        "classified_years": 11,
    }

    gate = study.evaluate_feasibility(diagnostics)

    assert gate["passed"] is False
    assert gate["checks"]["all_months_constructible"] is False


def test_cached_feasibility_attempt_skips_data_read(monkeypatch) -> None:
    """相同运行指纹存在时不得再次读取利润表。"""

    class CachedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: CachedAttempt(),
    )
    monkeypatch.setattr(study, "_data_version", lambda paths: "test")
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("不应读取数据")
        ),
    )

    result = study.run_study(object(), "20260724")  # type: ignore[arg-type]

    assert result == {"reused": True}


def _quarterly_rows() -> list[tuple[str, str, str, float]]:
    """生成足够计算8期历史误差的单票季度序列。"""
    rows: list[tuple[str, str, str, float]] = []
    quarter_ends = ["0331", "0630", "0930", "1231"]
    index = 0
    for year in range(2016, 2021):
        for quarter, suffix in enumerate(quarter_ends, start=1):
            end_date = f"{year}{suffix}"
            publish_month = {
                "0331": "0430",
                "0630": "0830",
                "0930": "1030",
                "1231": "0330",
            }[suffix]
            publish_year = year + 1 if suffix == "1231" else year
            publish_date = f"{publish_year}{publish_month}"
            eps = 0.05 * quarter + 0.01 * index + 0.002 * (index % 3)
            rows.append(("000001.SZ", end_date, publish_date, eps))
            index += 1
    return rows
