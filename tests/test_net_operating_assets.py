"""净经营资产点时数据与评分测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from data.net_operating_assets import (
    NetOperatingAssetsPaths,
    attach_net_operating_assets_database,
    create_net_operating_assets_signal_dates,
    materialize_net_operating_assets_asof,
)
from factors.net_operating_assets import score_net_operating_assets
from examples import net_operating_assets_feasibility_study as study
from examples import net_operating_assets_study as strategy_study


def _build_balance_db(path: Path) -> None:
    """构造最小年度资产负债表夹具。"""
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE default_table(
            ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR,
            f_ann_date VARCHAR, report_type VARCHAR, comp_type VARCHAR,
            total_assets DOUBLE, total_liab DOUBLE, money_cap DOUBLE,
            trad_asset DOUBLE, st_borr DOUBLE, lt_borr DOUBLE,
            bond_payable DOUBLE, st_bonds_payable DOUBLE,
            non_cur_liab_due_1y DOUBLE, lease_liab DOUBLE,
            update_flag VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO default_table VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "AAA.SZ", "20221231", "20230301", "20230301", "1", "1",
                1000, 600, 100, 50, 100, 100, 0, 0, 0, 0, "1",
            ),
            (
                "AAA.SZ", "20231231", "20240401", "20240401", "1", "1",
                1200, 700, 120, 60, 100, 120, 0, 0, 0, 0, "1",
            ),
        ],
    )
    connection.close()


def test_asof_uses_only_published_annual_report(tmp_path: Path) -> None:
    """信号日不得看到之后披露的年度报表。"""
    balance = tmp_path / "balance.duckdb"
    _build_balance_db(balance)
    connection = duckdb.connect()
    attach_net_operating_assets_database(
        connection,
        NetOperatingAssetsPaths(balance),
    )
    create_net_operating_assets_signal_dates(
        connection,
        ["20240331", "20240430"],
    )
    materialize_net_operating_assets_asof(connection)
    frame = connection.execute(
        """
        SELECT signal_date, report_period
        FROM net_operating_assets_asof
        ORDER BY signal_date
        """
    ).fetchdf()

    assert frame["report_period"].tolist() == ["20221231", "20231231"]


def test_noa_formula_and_score_direction(tmp_path: Path) -> None:
    """公式必须剔除现金和有息债务，且低NOA率得分更高。"""
    balance = tmp_path / "balance.duckdb"
    _build_balance_db(balance)
    connection = duckdb.connect()
    attach_net_operating_assets_database(
        connection,
        NetOperatingAssetsPaths(balance),
    )
    create_net_operating_assets_signal_dates(connection, ["20240331"])
    materialize_net_operating_assets_asof(connection)
    row = connection.execute(
        """
        SELECT operating_assets, operating_liabilities, noa_ratio
        FROM net_operating_assets_asof
        """
    ).fetchone()
    scored = score_net_operating_assets(
        pd.DataFrame(
            {"symbol": ["A", "B"], "noa_ratio": [0.2, 0.4]}
        )
    ).set_index("symbol")

    assert row[0] == 850.0
    assert row[1] == 400.0
    assert row[2] == 0.45
    assert scored.loc["A", "factor_score"] > scored.loc["B", "factor_score"]


def test_feasibility_rejects_insufficient_monthly_coverage() -> None:
    """候选池广度不足时不得读取未来收益。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131", "20240229"],
            "symbol": ["A", "B"],
            "noa_ratio": [0.2, 0.3],
        }
    )
    monthly = pd.DataFrame(
        {
            "signal_date": ["20240131", "20240229"],
            "candidate_count": [499, 499],
            "unique_factor_values": [499, 499],
            "top40_count": [40, 40],
            "top40_median_adv_rmb": [30_000_000.0, 30_000_000.0],
            "top40_tradable_share": [1.0, 1.0],
            "spearman_ret120": [0.1, 0.1],
            "spearman_vol60": [0.1, 0.1],
            "spearman_log_adv": [0.1, 0.1],
        }
    )
    diagnostics = {
        "visibility_violations": 0.0,
        "duplicate_signal_symbol_rows": 0.0,
        "formula_identity_violations": 0.0,
        "money_cap_missing_share": 0.0,
        "trading_asset_missing_share": 0.5,
        "all_debt_components_missing_share": 0.5,
    }

    result = study.evaluate_feasibility(
        candidates,
        monthly,
        diagnostics,
        "20240229",
    )

    assert result["passed"] is False
    assert result["checks"]["qualified_month_share"] is False


def test_feasibility_reuses_same_fingerprint_without_scan(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """相同因子语义和数据版本必须复用，禁止重复扫描。"""
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
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("不应重新扫描")
        ),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_strategy_selects_lowest_noa_ratio() -> None:
    """正式组合必须选择 NOA 率最低的一组，而不是最高的一组。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 41,
            "symbol": [f"S{index:03d}" for index in range(41)],
            "noa_ratio": [index / 100.0 for index in range(41)],
        }
    )

    targets, holdings, counts = strategy_study.build_targets(candidates)

    assert "S040" not in targets["20240131"]
    assert set(holdings["symbol"]) == {
        f"S{index:03d}" for index in range(40)
    }
    assert counts["latest"] == 41.0


def test_strategy_definition_uses_grid_risk_overlay() -> None:
    """正式研究必须显式启用冻结风险层，不能误用 FIXED 空实现。"""
    risk = strategy_study.RESEARCH_SPEC.definition["risk_overlay"]

    assert risk == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }
