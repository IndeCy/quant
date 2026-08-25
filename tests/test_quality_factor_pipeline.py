"""Quality 特征标准入口和旧 V1 兼容性测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from pandas.testing import assert_frame_equal

from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    load_quality_financial_snapshot,
    materialize_quality_financial_asof,
)
from examples.quality_strategy_v1 import score_quality_frame as legacy_score_quality_frame
from factors.quality import QUALITY_COLUMNS, score_quality_frame, winsorize_series, zscore_series
from factors.quality_fundamental import score_quality_fundamental_frame
from factors.quality_market_extension import score_quality_market_extension
from portfolio.topn import build_topn_selections
from strategies.quality_signal import build_quality_scores
from strategies.quality_universe import apply_quality_universe_filters


def test_standard_quality_score_matches_frozen_v1_export() -> None:
    """旧研究入口必须直接复用标准实现，避免 ML 产生第二套分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["C", "A", "B", "D", "E"],
            "roe": [8.0, 10.0, 20.0, 30.0, 100.0],
            "roa": [2.0, 5.0, 6.0, 9.0, 50.0],
            "ocf_to_or": [-2.0, 10.0, 8.0, 12.0, 80.0],
        }
    )

    expected = legacy_score_quality_frame(frame)
    actual = score_quality_frame(frame)

    assert legacy_score_quality_frame is score_quality_frame
    assert_frame_equal(actual, expected)
    assert list(actual.columns[-4:]) == ["roe_z", "roa_z", "ocf_to_or_z", "quality_score"]


def test_quality_score_preserves_frozen_transform_semantics() -> None:
    """缩尾和总体标准差口径必须与 Quality V1 一致。"""
    values = pd.Series([0.0, 10.0, 20.0, 30.0, 100.0])
    clipped = winsorize_series(values)
    expected = (clipped - clipped.mean()) / clipped.std(ddof=0)

    assert_frame_equal(zscore_series(clipped).to_frame(), expected.to_frame())


def test_quality_universe_filters_point_in_time_status() -> None:
    """上市、ST、退市和年度报告过滤全部按信号日执行。"""
    base = {
        "signal_date": "20240131",
        "list_date": "20100101",
        "delist_date": None,
        "st_name": None,
        "end_date": "20221231",
        "roe": 10.0,
        "roa": 5.0,
        "ocf_to_or": 8.0,
    }
    rows = [
        {**base, "symbol": "OK", "name": "正常公司"},
        {**base, "symbol": "NEW", "name": "新公司", "list_date": "20230101"},
        {**base, "symbol": "ST", "name": "ST公司", "st_name": "ST公司"},
        {**base, "symbol": "DELIST", "name": "退市公司", "delist_date": "20230101"},
        {**base, "symbol": "QUARTER", "name": "季度公司", "end_date": "20230930"},
    ]

    result = apply_quality_universe_filters(pd.DataFrame(rows), quantile_filter=False)

    assert result["symbol"].tolist() == ["OK"]
    assert result[QUALITY_COLUMNS].notna().all().all()


def test_quality_scores_delegate_topn_to_portfolio_layer() -> None:
    """策略生成分数，组合层稳定决定 TopN 和排名。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 3,
            "symbol": ["B", "A", "C"],
            "roe": [10.0, 10.0, 5.0],
            "roa": [10.0, 10.0, 5.0],
            "ocf_to_or": [10.0, 10.0, 5.0],
        }
    )
    scores = build_quality_scores(candidates)

    selections, holdings = build_topn_selections(scores, "quality_score", 2)

    assert selections == {"20240131": ["A", "B"]}
    assert holdings[["symbol", "rank"]].to_dict("records") == [
        {"symbol": "A", "rank": 1},
        {"symbol": "B", "rank": 2},
    ]


def test_quality_fundamental_score_respects_factor_direction() -> None:
    """资产增长和负债率声明为负向后，高值必须降低综合得分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "roa": [8.0, 8.0, 8.0],
            "ocf_to_or": [10.0, 10.0, 10.0],
            "assets_yoy": [5.0, 15.0, 30.0],
            "debt_to_assets": [20.0, 40.0, 70.0],
        }
    )

    scored = score_quality_fundamental_frame(
        frame,
        {
            "roa": 1,
            "ocf_to_or": 1,
            "assets_yoy": -1,
            "debt_to_assets": -1,
        },
    )

    assert scored["symbol"].tolist() == ["A", "B", "C"]
    assert scored["factor_score"].is_monotonic_decreasing


def test_quality_market_extension_keeps_quality_as_core_score() -> None:
    """增强因子只能占声明的小权重，不能替换冻结Quality主体。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "roe": [20.0, 10.0, 5.0],
            "roa": [10.0, 8.0, 4.0],
            "ocf_to_or": [15.0, 9.0, 3.0],
            "momentum_120d": [-0.1, 0.0, 0.5],
        }
    )

    scored = score_quality_market_extension(frame, {"momentum_120d": 0.15})

    assert scored["symbol"].iloc[0] == "A"
    assert "quality_score" in scored
    assert "momentum_120d_z" in scored


def test_financial_asof_snapshot_hides_unpublished_and_non_annual_rows(tmp_path: Path) -> None:
    """财务截面只能看到信号日已披露的 1231 年报。"""
    paths = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_quality_signal_date_table(connection, ["20230429", "20230430", "20240501"])
        attach_quality_financial_databases(connection, paths)
        materialize_quality_financial_asof(connection, annual_only=True)

        snapshot = load_quality_financial_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["signal_date"].tolist() == ["20230430", "20240501"]
    assert snapshot["end_date"].tolist() == ["20221231", "20231231"]
    assert (snapshot["f_ann_date"] <= snapshot["signal_date"]).all()
    assert snapshot["end_date"].str.endswith("1231").all()
    assert snapshot.iloc[-1]["ocf_to_profit"] == 82.0
    assert snapshot.iloc[-1]["grossprofit_margin"] == 37.0
    assert snapshot.iloc[-1]["assets_yoy"] == 6.0


def _build_financial_databases(tmp_path: Path) -> QualityFinancialPaths:
    """构造带年度和季度记录的最小 DuckDB 财务夹具。"""
    indicator = tmp_path / "fina.duckdb"
    with duckdb.connect(str(indicator)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR, end_date VARCHAR, roe DOUBLE, roa DOUBLE,
                ocf_to_or DOUBLE, ocf_to_profit DOUBLE,
                grossprofit_margin DOUBLE, netprofit_margin DOUBLE,
                assets_yoy DOUBLE, roic DOUBLE, assets_turn DOUBLE,
                salescash_to_or DOUBLE, dtprofit_to_profit DOUBLE,
                netprofit_yoy DOUBLE, eps DOUBLE, bps DOUBLE,
                debt_to_assets DOUBLE, tr_yoy DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20221231", 10.0, 5.0, 8.0, 80.0, 35.0, 20.0, 4.0, 6.0, 0.8, 90.0, 95.0, 8.0, 1.0, 5.0, 30.0, 6.0),
                ("AAA.SZ", "20230331", 11.0, 6.0, 9.0, 81.0, 36.0, 21.0, 5.0, 7.0, 0.9, 91.0, 96.0, 9.0, 1.1, 5.1, 31.0, 7.0),
                ("AAA.SZ", "20231231", 12.0, 7.0, 10.0, 82.0, 37.0, 22.0, 6.0, 8.0, 1.0, 92.0, 97.0, 10.0, 1.2, 5.2, 32.0, 8.0),
            ],
        )
    statement_paths: list[Path] = []
    for name in ["income", "balance", "cashflow"]:
        path = tmp_path / f"{name}.duckdb"
        statement_paths.append(path)
        with duckdb.connect(str(path)) as connection:
            connection.execute(
                "CREATE TABLE default_table(ts_code VARCHAR, end_date VARCHAR, f_ann_date VARCHAR)"
            )
            connection.executemany(
                "INSERT INTO default_table VALUES (?, ?, ?)",
                [
                    ("AAA.SZ", "20221231", "20230430"),
                    ("AAA.SZ", "20230331", "20230420"),
                    ("AAA.SZ", "20231231", "20240430"),
                ],
            )
    return QualityFinancialPaths(indicator, *statement_paths)
