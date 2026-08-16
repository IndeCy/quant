"""经营现金流稳定性点时门面和评分测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.operating_cashflow_stability import (
    OperatingCashflowStabilityPaths,
    attach_operating_cashflow_databases,
    create_operating_cashflow_signal_dates,
    load_operating_cashflow_stability_snapshot,
    materialize_operating_cashflow_stability_asof,
)
from factors.operating_cashflow_stability import (
    score_operating_cashflow_stability,
)
from examples import operating_cashflow_stability_study as strategy_study
from examples import operating_cashflow_stability_feasibility_study as study


def test_five_year_window_obeys_each_signal_date(tmp_path: Path) -> None:
    """新年报披露前后必须分别使用不同的连续五年窗口。"""
    cashflow, balance = _build_financial_databases(tmp_path)
    connection = duckdb.connect(":memory:")
    try:
        create_operating_cashflow_signal_dates(
            connection,
            ["20240429", "20240430"],
        )
        attach_operating_cashflow_databases(
            connection,
            OperatingCashflowStabilityPaths(cashflow, balance),
        )
        materialize_operating_cashflow_stability_asof(connection)
        frame = load_operating_cashflow_stability_snapshot(connection)
    finally:
        connection.close()

    assert frame["latest_fiscal_year"].tolist() == [2022, 2023]
    assert frame["latest_publish_date"].tolist() == ["20230331", "20240430"]
    assert frame["observations"].tolist() == [5, 5]


def test_score_excludes_stable_cash_burn_and_prefers_low_volatility() -> None:
    """长期现金流为负不能因波动低而入选。"""
    frame = pd.DataFrame(
        {
            "symbol": ["STABLE", "VOLATILE", "BURN"],
            "ocf_assets_median_5y": [0.10, 0.10, -0.10],
            "ocf_assets_std_5y": [0.01, 0.05, 0.001],
        }
    )

    scored = score_operating_cashflow_stability(frame).set_index("symbol")

    assert set(scored.index) == {"STABLE", "VOLATILE"}
    assert scored.loc["STABLE", "factor_score"] > scored.loc[
        "VOLATILE",
        "factor_score",
    ]


def test_strategy_selects_lowest_cashflow_volatility() -> None:
    """正式组合必须选正现金流中的最低波动 Top40。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 41,
            "symbol": [f"S{index:03d}" for index in range(41)],
            "ocf_assets_median_5y": [0.1] * 41,
            "ocf_assets_std_5y": [index / 100.0 for index in range(41)],
        }
    )

    targets, holdings, counts = strategy_study.build_targets(candidates)

    assert "S040" not in targets["20240131"]
    assert set(holdings["symbol"]) == {
        f"S{index:03d}" for index in range(40)
    }
    assert counts["latest"] == 41.0


def test_strategy_definition_uses_grid_risk_overlay() -> None:
    """冻结风险层必须显式启用 GRID 模式。"""
    assert strategy_study.RESEARCH_SPEC.definition["risk_overlay"] == {
        "mode": "GRID",
        "window": 20,
        "threshold": 0.45,
        "reduced_exposure": 0.30,
    }


def test_feasibility_reuses_same_fingerprint_without_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同数据与定义必须复用，禁止重复扫描财务大表。"""
    _seed_runtime_files(tmp_path)

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


def test_strategy_reuses_same_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """正式策略命中同一指纹时不得重复运行 M0。"""
    _seed_runtime_files(tmp_path)

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
    """构造六份现金流和七份资产负债表。"""
    cashflow = tmp_path / "cashflow.duckdb"
    balance = tmp_path / "balancesheet.duckdb"
    with duckdb.connect(str(cashflow)) as connection:
        connection.execute(
            """
            CREATE TABLE default_table(
                ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR,
                f_ann_date VARCHAR, report_type VARCHAR, comp_type VARCHAR,
                n_cashflow_act DOUBLE, update_flag VARCHAR
            )
            """
        )
        rows = []
        for year in range(2018, 2024):
            publish = (
                "20240430"
                if year == 2023
                else f"{year + 1}0331"
            )
            rows.append(
                (
                    "AAA.SZ",
                    f"{year}1231",
                    publish,
                    publish,
                    "1",
                    "1",
                    float(10 + year - 2018),
                    "1",
                )
            )
        connection.executemany(
            "INSERT INTO default_table VALUES (?,?,?,?,?,?,?,?)",
            rows,
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
        rows = []
        for year in range(2017, 2024):
            publish = (
                "20240430"
                if year == 2023
                else f"{year + 1}0331"
            )
            rows.append(
                (
                    "AAA.SZ",
                    f"{year}1231",
                    publish,
                    publish,
                    "1",
                    "1",
                    100.0,
                    "1",
                )
            )
        connection.executemany(
            "INSERT INTO default_table VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
    return cashflow, balance


def _seed_runtime_files(tmp_path: Path) -> None:
    """创建研究指纹所需的最小文件集合。"""
    files = [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "fina_indicator.duckdb",
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "cashflow.duckdb",
        tmp_path / "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
        tmp_path / "data" / "benchmark_increment.duckdb",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
