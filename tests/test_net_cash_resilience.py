"""净现金财务韧性数据门面、因子和研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.net_cash_resilience import (
    NetCashResiliencePaths,
    attach_net_cash_database,
    create_net_cash_signal_date_table,
    load_net_cash_resilience_snapshot,
    materialize_net_cash_resilience_asof,
)
from examples import net_cash_resilience_feasibility_study as study
from factors.net_cash_resilience import score_net_cash_resilience_frame


def _create_balance_database(path: Path) -> None:
    """创建只包含本因子依赖字段的资产负债表夹具。"""
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE default_table(
            ts_code VARCHAR,
            end_date VARCHAR,
            ann_date VARCHAR,
            f_ann_date VARCHAR,
            report_type VARCHAR,
            comp_type VARCHAR,
            update_flag VARCHAR,
            money_cap DOUBLE,
            total_assets DOUBLE,
            st_borr DOUBLE,
            lt_borr DOUBLE,
            bond_payable DOUBLE,
            non_cur_liab_due_1y DOUBLE,
            st_fin_payable DOUBLE,
            lease_liab DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "000001.SZ",
                "20221231",
                "20230320",
                "20230320",
                "1",
                "1",
                "0",
                30.0,
                100.0,
                5.0,
                5.0,
                None,
                None,
                None,
                None,
            ),
            (
                "000001.SZ",
                "20221231",
                "20230410",
                "20230410",
                "1",
                "1",
                "1",
                40.0,
                100.0,
                5.0,
                5.0,
                None,
                None,
                None,
                None,
            ),
            (
                "000001.SZ",
                "20231231",
                "20240320",
                "20240320",
                "1",
                "1",
                "0",
                90.0,
                100.0,
                0.0,
                0.0,
                None,
                None,
                None,
                None,
            ),
        ],
    )
    connection.close()


def test_asof_uses_latest_visible_revision_and_blocks_future_report(
    tmp_path: Path,
) -> None:
    """信号日只能看见当时已披露的最新年报修订。"""
    database = tmp_path / "balance.duckdb"
    _create_balance_database(database)
    connection = duckdb.connect()
    try:
        create_net_cash_signal_date_table(connection, ["20230630"])
        attach_net_cash_database(
            connection,
            NetCashResiliencePaths(database),
        )
        materialize_net_cash_resilience_asof(connection)
        snapshot = load_net_cash_resilience_snapshot(connection)
    finally:
        connection.close()

    assert len(snapshot) == 1
    row = snapshot.iloc[0]
    assert row["report_period"] == "20221231"
    assert row["publish_date"] == "20230410"
    assert row["net_cash_to_assets"] == pytest.approx(0.30)
    assert row["reported_debt_item_count"] == 2


def test_factor_prefers_more_net_cash_without_hiding_missing_debt_flag() -> None:
    """净现金越高得分越高，债务字段覆盖仍保留给研究门禁。"""
    frame = pd.DataFrame(
        {
            "symbol": ["CASH_RICH", "LEVERED"],
            "net_cash_to_assets": [0.40, -0.30],
            "reported_debt_item_count": [0, 4],
        }
    )

    scored = score_net_cash_resilience_frame(frame).set_index("symbol")

    assert scored.loc["CASH_RICH", "factor_score"] > scored.loc[
        "LEVERED", "factor_score"
    ]
    assert scored.loc["CASH_RICH", "reported_debt_item_count"] == 0


def test_factor_filters_non_finite_and_impossible_ratios() -> None:
    """非有限值及明显越界的资产比例不得进入排序。"""
    frame = pd.DataFrame(
        {
            "symbol": ["VALID", "TOO_HIGH", "TOO_LOW", "NAN"],
            "net_cash_to_assets": [0.20, 1.20, -6.0, float("nan")],
            "reported_debt_item_count": [3, 3, 3, 3],
        }
    )

    result = score_net_cash_resilience_frame(frame)

    assert result["symbol"].tolist() == ["VALID"]


def test_feasibility_rejects_unreported_debt_pollution() -> None:
    """Top40 大量债务字段空缺时不得把缺失误认作零负债 Alpha。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20231229", "20240131", "20240229"],
            "candidate_count": [1200, 1200, 1200],
            "unique_factor_values": [1000, 1000, 1000],
            "top40_unreported_debt_share": [0.10, 0.30, 0.30],
            "top40_median_adv_rmb": [20_000_000.0] * 3,
            "top40_tradable_share": [1.0] * 3,
        }
    )

    result = study.evaluate_feasibility(
        monthly,
        {
            "ratio_p01": -0.5,
            "ratio_median": 0.1,
            "ratio_p99": 0.8,
            "unreported_debt_share": 0.1,
            "zero_interest_debt_share": 0.2,
        },
        {
            "duplicate_signal_symbol_rows": 0,
            "visibility_violations": 0,
            "range_violations": 0,
            "median_spearman_with_amount20": 0.0,
            "median_spearman_with_vol60": 0.0,
            "median_spearman_with_ret120": 0.0,
        },
        "20240229",
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_feasibility_reuses_fingerprint_without_data_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同研究指纹应复用历史结论，不再扫描财务大表。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"fixture")
    (tmp_path / "balancesheet.duckdb").write_bytes(b"fixture")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"fixture")

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
        lambda *args, **kwargs: pytest.fail("不应读取研究数据"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
