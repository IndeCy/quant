"""低应计利润质量研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.accrual_quality import (
    AccrualQualityPaths,
    attach_accrual_quality_databases,
    create_accrual_signal_date_table,
    load_accrual_quality_snapshot,
    materialize_accrual_quality_asof,
)
from examples import accrual_quality_study as study
from factors.accrual_quality import score_low_accrual_frame


def _create_financial_databases(tmp_path: Path) -> AccrualQualityPaths:
    """创建公告日错开的三表年度财务数据。"""
    income = tmp_path / "income.duckdb"
    cashflow = tmp_path / "cashflow.duckdb"
    balance = tmp_path / "balancesheet.duckdb"

    connection = duckdb.connect(str(income))
    connection.execute(
        """
        CREATE TABLE default_table (
            ts_code VARCHAR,
            end_date VARCHAR,
            f_ann_date VARCHAR,
            n_income_attr_p DOUBLE
        )
        """
    )
    connection.execute(
        "INSERT INTO default_table VALUES ('000001.SZ', '20221231', '20230310', 100)"
    )
    connection.close()

    connection = duckdb.connect(str(cashflow))
    connection.execute(
        """
        CREATE TABLE default_table (
            ts_code VARCHAR,
            end_date VARCHAR,
            f_ann_date VARCHAR,
            n_cashflow_act DOUBLE
        )
        """
    )
    connection.execute(
        "INSERT INTO default_table VALUES ('000001.SZ', '20221231', '20230320', 70)"
    )
    connection.close()

    connection = duckdb.connect(str(balance))
    connection.execute(
        """
        CREATE TABLE default_table (
            ts_code VARCHAR,
            end_date VARCHAR,
            f_ann_date VARCHAR,
            total_assets DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO default_table VALUES (?, ?, ?, ?)",
        [
            ("000001.SZ", "20211231", "20220315", 800),
            ("000001.SZ", "20221231", "20230315", 1000),
        ],
    )
    connection.close()
    return AccrualQualityPaths(income=income, balance=balance, cashflow=cashflow)


def test_accrual_asof_waits_for_all_statements_and_uses_average_assets(
    tmp_path: Path,
) -> None:
    """三表中最晚公告日前不可见，公告后使用两年平均资产。"""
    paths = _create_financial_databases(tmp_path)
    connection = duckdb.connect()
    try:
        create_accrual_signal_date_table(connection, ["20230319", "20230321"])
        attach_accrual_quality_databases(connection, paths)
        materialize_accrual_quality_asof(connection)
        snapshot = load_accrual_quality_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["signal_date"].tolist() == ["20230321"]
    row = snapshot.iloc[0]
    assert row["publish_date"] == "20230320"
    assert row["average_total_assets"] == pytest.approx(900)
    assert row["accrual_ratio"] == pytest.approx((100 - 70) / 900)


def test_low_accrual_factor_prefers_cash_backed_profit_and_excludes_losses() -> None:
    """现金流更强的正利润公司应获得更高分，亏损公司被排除。"""
    frame = pd.DataFrame(
        [
            _factor_row("CASH_BACKED", 100, 180, 1000),
            _factor_row("ACCRUAL_HEAVY", 100, 20, 1000),
            _factor_row("LOSS", -100, 100, 1000),
        ]
    )

    result = score_low_accrual_frame(frame).set_index("symbol")

    assert set(result.index) == {"CASH_BACKED", "ACCRUAL_HEAVY"}
    assert (
        result.loc["CASH_BACKED", "factor_score"]
        > result.loc["ACCRUAL_HEAVY", "factor_score"]
    )


def test_low_accrual_factor_requires_standard_columns() -> None:
    """缺失门面字段时因子必须显式失败。"""
    with pytest.raises(ValueError, match="accrual_ratio"):
        score_low_accrual_frame(
            pd.DataFrame(
                {
                    "symbol": ["A"],
                    "net_income": [1],
                    "operating_cashflow": [1],
                    "average_total_assets": [1],
                }
            )
        )


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同财务快照和研究定义不得重复回测。"""
    for name in ["income.duckdb", "balancesheet.duckdb", "cashflow.duckdb"]:
        (tmp_path / name).write_bytes(b"test")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study.STRATEGY_ID}

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

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _factor_row(
    symbol: str,
    net_income: float,
    operating_cashflow: float,
    average_total_assets: float,
) -> dict[str, object]:
    """生成一条应计利润因子输入。"""
    return {
        "symbol": symbol,
        "net_income": net_income,
        "operating_cashflow": operating_cashflow,
        "average_total_assets": average_total_assets,
        "accrual_ratio": (
            net_income - operating_cashflow
        ) / average_total_assets,
    }
