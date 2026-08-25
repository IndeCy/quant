"""Quality ML point-in-time 数据集测试。"""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.quality_financial import QualityFinancialPaths
from ml.contracts import DatasetSpec
from ml.dataset import build_quality_ml_dataset


SIGNAL_DATES = ["20230131", "20230228", "20230331"]


def test_dataset_is_point_in_time_and_keeps_unlabeled_latest_snapshot(tmp_path: Path) -> None:
    """财务特征遵守公告日，最新推理截面允许没有未来标签。"""
    connection, paths = _build_dataset_fixture(tmp_path)
    try:
        dataset = build_quality_ml_dataset(connection, paths, signal_dates=SIGNAL_DATES)
    finally:
        connection.close()

    frame = dataset.frame
    assert frame["end_date"].tolist() == ["20211231"] * 3
    assert (frame["f_ann_date"] <= frame["signal_date"]).all()
    assert frame.loc[frame["signal_date"].eq("20230131"), "forward_return"].iloc[0] == pytest.approx(0.10)
    assert pd.isna(frame.loc[frame["signal_date"].eq("20230331"), "forward_rank"].iloc[0])
    assert dataset.manifest.row_count == 3
    assert dataset.manifest.trainable_count == 2
    assert dataset.manifest.as_of_violation_count == 0
    assert len(dataset.manifest.dataset_hash) == 64


def test_future_column_cannot_be_declared_as_feature(tmp_path: Path) -> None:
    """任何 forward 字段进入模型特征都必须被数据门禁拒绝。"""
    connection, paths = _build_dataset_fixture(tmp_path)
    spec = DatasetSpec(features=("roe", "roa", "ocf_to_or", "forward_return"))
    try:
        with pytest.raises(ValueError, match="future columns"):
            build_quality_ml_dataset(connection, paths, spec=spec, signal_dates=SIGNAL_DATES)
    finally:
        connection.close()


def _build_dataset_fixture(tmp_path: Path) -> tuple[duckdb.DuckDBPyConnection, QualityFinancialPaths]:
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE features(
            trade_date VARCHAR, symbol VARCHAR, open DOUBLE, close DOUBLE, raw_close DOUBLE,
            adj_factor DOUBLE, vol60 DOUBLE, ret20 DOUBLE, ret120 DOUBLE,
            ma60 DOUBLE, ma120 DOUBLE, amount20 DOUBLE, amount60 DOUBLE,
            downside_vol60 DOUBLE, worst_ret60 DOUBLE, amount DOUBLE,
            amount_p20 DOUBLE, volume DOUBLE, st_name VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            _feature_row("20230131", 9.0),
            _feature_row("20230201", 10.0),
            _feature_row("20230228", 10.5),
            _feature_row("20230301", 11.0),
            _feature_row("20230331", 11.5),
            _feature_row("20230403", 12.0),
        ],
    )
    connection.execute(
        "CREATE TABLE stock_basic(ts_code VARCHAR, name VARCHAR, list_status VARCHAR, list_date VARCHAR, delist_date VARCHAR)"
    )
    connection.execute("INSERT INTO stock_basic VALUES ('AAA.SZ', '测试公司', 'L', '20100101', NULL)")
    connection.execute(
        "CREATE TABLE stock_namechange(ts_code VARCHAR, name VARCHAR, start_date VARCHAR, end_date VARCHAR)"
    )
    connection.execute(
        "CREATE TABLE stock_name_manual(ts_code VARCHAR, name VARCHAR, start_date VARCHAR, end_date VARCHAR)"
    )

    indicator = tmp_path / "fina.duckdb"
    with duckdb.connect(str(indicator)) as target:
        target.execute(
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
        target.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20211231", 10.0, 5.0, 8.0, 80.0, 35.0, 20.0, 4.0, 6.0, 0.8, 90.0, 95.0, 8.0, 1.0, 5.0, 30.0, 6.0),
                ("AAA.SZ", "20221231", 20.0, 9.0, 12.0, 85.0, 38.0, 22.0, 5.0, 10.0, 0.9, 92.0, 96.0, 10.0, 1.2, 5.5, 28.0, 8.0),
            ],
        )
    statement_paths: list[Path] = []
    for name in ["income", "balance", "cashflow"]:
        path = tmp_path / f"{name}.duckdb"
        statement_paths.append(path)
        with duckdb.connect(str(path)) as target:
            target.execute(
                "CREATE TABLE default_table(ts_code VARCHAR, end_date VARCHAR, f_ann_date VARCHAR)"
            )
            target.executemany(
                "INSERT INTO default_table VALUES (?, ?, ?)",
                [
                    ("AAA.SZ", "20211231", "20220430"),
                    ("AAA.SZ", "20221231", "20230430"),
                ],
            )
    return connection, QualityFinancialPaths(indicator, *statement_paths)


def _feature_row(trade_date: str, price: float) -> tuple[object, ...]:
    """构造包含标准研究特征的单票行情行。"""
    return (
        trade_date, "AAA.SZ", price, price, price, 1.0, 0.02,
        0.01, 0.05, price, price, 100.0, 100.0, 0.01, -0.03,
        100.0, 20.0, 10.0, None,
    )
