"""净股本发行点时序列和可辨识性门槛测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.net_share_issuance import (
    NetShareIssuancePaths,
    attach_net_share_issuance_database,
    create_net_share_issuance_signal_dates,
    load_net_share_issuance_snapshot,
    materialize_net_share_issuance_asof,
)
from examples import net_share_issuance_feasibility_study as study
from examples import net_share_issuance_feasibility_v2_study as v2_study


def test_snapshot_switches_only_after_latest_report_is_visible(
    tmp_path: Path,
) -> None:
    """新年报披露前只能看到上一组连续年度股本。"""
    balance = _build_balance_database(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        _seed_adjustment_factors(connection)
        create_net_share_issuance_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_net_share_issuance_database(
            connection,
            NetShareIssuancePaths(balance),
        )
        materialize_net_share_issuance_asof(connection)
        snapshot = load_net_share_issuance_snapshot(connection)
    finally:
        connection.close()

    before = snapshot[snapshot["signal_date"].eq("20240429")].iloc[0]
    after = snapshot[snapshot["signal_date"].eq("20240430")].iloc[0]
    assert before["report_period"] == "20221231"
    assert float(before["net_share_growth"]) == pytest.approx(-0.10)
    assert after["report_period"] == "20231231"
    assert float(after["net_share_growth"]) == pytest.approx(-0.20)


def test_share_and_adjustment_change_is_marked_ambiguous(
    tmp_path: Path,
) -> None:
    """股本与复权因子同步大变时不得直接解释为增发。"""
    balance = _build_balance_database(tmp_path, latest_shares=180.0)
    connection = duckdb.connect(":memory:")
    try:
        _seed_adjustment_factors(connection, latest_factor=2.0)
        create_net_share_issuance_signal_dates(connection, ["20240430"])
        attach_net_share_issuance_database(
            connection,
            NetShareIssuancePaths(balance),
        )
        materialize_net_share_issuance_asof(connection)
        row = load_net_share_issuance_snapshot(connection).iloc[0]
    finally:
        connection.close()

    assert bool(row["corporate_action_ambiguous"]) is True


def test_feasibility_rejects_zero_value_top40_tie() -> None:
    """缩股公司不足时必须在回测前拒绝代码排序伪组合。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131"],
            "candidate_count": [1000, 1100],
            "negative_issuer_count": [5, 10],
        }
    )
    distribution = {
        "p01": -0.01,
        "median": 0.0,
        "p99": 0.20,
        "unchanged_share": 0.90,
    }
    diagnostics = {
        "visibility_violations": 0.0,
        "duplicate_signal_symbol_rows": 0.0,
        "adjustment_missing_share": 0.0,
        "corporate_action_ambiguous_share": 0.02,
    }

    result = study.evaluate_feasibility(
        monthly,
        distribution,
        diagnostics,
        "20220131",
    )

    assert result["passed"] is False
    assert result["checks"]["distinguishable_month_share"] is False


def test_feasibility_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义和数据版本必须复用，不重复扫描历史股本。"""
    files = [
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


def test_v2_diagnostics_use_only_given_investable_source() -> None:
    """V2覆盖分母只能来自已完成标准股票池过滤的记录。"""
    source = pd.DataFrame(
        {
            "signal_date": ["20240430", "20240430"],
            "symbol": ["VALID", "MISSING"],
            "publish_date": ["20240401", "20240401"],
            "prior_publish_date": ["20230401", "20230401"],
            "adjustment_available": [True, False],
            "corporate_action_ambiguous": [False, False],
        }
    )

    result = v2_study.build_investable_diagnostics(source)

    assert result["adjustment_missing_share"] == pytest.approx(0.5)
    assert result["visibility_violations"] == 0


def test_v2_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V2相同定义也必须命中确定性研究指纹。"""
    files = [
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
            return {"reused": True, "experiment_id": v2_study.EXPERIMENT_ID}

    monkeypatch.setattr(
        v2_study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        v2_study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = v2_study.run_study(v2_study.RuntimePaths(tmp_path), "20260725")

    assert result["reused"] is True


def _build_balance_database(
    tmp_path: Path,
    *,
    latest_shares: float = 72.0,
) -> Path:
    """构造三年连续股本，2023年报于2024-04-30披露。"""
    path = tmp_path / "balancesheet.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR,
                end_date VARCHAR,
                ann_date VARCHAR,
                f_ann_date VARCHAR,
                update_flag VARCHAR,
                total_share DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("AAA.SZ", "20211231", "20220401", "20220401", "1", 100.0),
                ("AAA.SZ", "20221231", "20230401", "20230401", "1", 90.0),
                (
                    "AAA.SZ", "20231231", "20240430", "20240430", "1",
                    latest_shares,
                ),
            ],
        )
    return path


def _seed_adjustment_factors(
    connection: duckdb.DuckDBPyConnection,
    *,
    latest_factor: float = 1.0,
) -> None:
    """提供报告期最近交易日复权因子。"""
    connection.execute(
        """
        CREATE TABLE daily_adj_cache(
            ts_code VARCHAR,
            trade_date VARCHAR,
            adj_factor DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO daily_adj_cache VALUES (?, ?, ?)",
        [
            ("AAA.SZ", "20211231", 1.0),
            ("AAA.SZ", "20221230", 1.0),
            ("AAA.SZ", "20231229", latest_factor),
        ],
    )
