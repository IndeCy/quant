"""Quality Value LowVol 生产候选的关键契约测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.benchmark_series import load_adjusted_fund_curve
from data.quality_value_lowvol import build_quality_value_lowvol_candidates
from factors.quality_value_lowvol import FACTOR_COLUMNS, score_quality_value_lowvol_frame
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_definition_loader import load_strategy_definition
from strategies.quality_balanced_value_signal import build_quality_balanced_value_topn
from strategies.quality_value_lowvol_runner import _target_changed


def test_five_factor_score_uses_frozen_equal_weight_contract() -> None:
    """五因子必须全部进入 1/99 缩尾与等权综合分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "roa": [1.0, 2.0, 3.0],
            "ocf_to_or": [1.0, 2.0, 3.0],
            "earnings_yield": [0.01, 0.02, 0.03],
            "book_yield": [0.1, 0.2, 0.3],
            "low_volatility_60d": [-0.3, -0.2, -0.1],
        }
    )
    weights = {factor_id: 0.2 for factor_id in FACTOR_COLUMNS}

    result = score_quality_value_lowvol_frame(frame, weights)

    assert result["symbol"].tolist() == ["C", "B", "A"]
    assert result.loc[result["symbol"].eq("B"), "factor_score"].iloc[0] == pytest.approx(0.0)


def test_corporate_action_gate_rejects_material_adjustment_change() -> None:
    """公告日至信号日发生重大复权变化时，不允许直接使用旧每股指标。"""
    frame = pd.DataFrame(
        [
            _candidate("STABLE", 1.0, 1.0),
            _candidate("DIVIDEND", 1.0, 1.05),
            _candidate("CHANGED", 1.0, 1.2),
            _candidate("MISSING", None, 1.0),
        ]
    )

    result, audit = build_quality_value_lowvol_candidates(frame)

    assert result["symbol"].tolist() == ["STABLE", "DIVIDEND"]
    assert result.iloc[0]["earnings_yield"] == pytest.approx(0.1)
    assert result.iloc[0]["book_yield"] == pytest.approx(0.5)
    assert result.iloc[0]["low_volatility_60d"] == pytest.approx(-0.02)
    assert audit.changed_rows == 2
    assert audit.excluded_rows == 1
    assert audit.missing_rows == 1
    assert audit.materiality_threshold == pytest.approx(0.10)


def test_failed_risk_candidate_is_versioned_and_retired() -> None:
    """风险实验失败后必须保留版本，但不能进入每日 Paper 批处理。"""
    definition = load_strategy_definition("quality_value_lowvol_v0")

    assert definition.status == "retired"
    assert definition.enabled is False
    assert definition.adjust_policy == "qfq"
    assert definition.execution_policy == "m0_t1"
    assert definition.risk_overlay == "vol_20_45_to_30"
    assert [factor.factor_id for factor in definition.factors] == list(FACTOR_COLUMNS)


def test_balanced_value_candidate_has_frozen_weights_and_topn() -> None:
    """Paper候选必须复现Quality 80%、E/P 10%、B/P 10%的研究口径。"""
    definition = load_strategy_definition("quality_balanced_value_v1")
    rows = []
    for symbol, value in [("A", 3.0), ("B", 2.0), ("C", 1.0)]:
        rows.append(
            {
                "signal_date": "20260630",
                "symbol": symbol,
                "roe": value,
                "roa": value,
                "ocf_to_or": value,
                "earnings_yield": value / 100,
                "book_yield": value / 10,
            }
        )

    selections, holdings = build_quality_balanced_value_topn(
        pd.DataFrame(rows),
        {factor.factor_id: factor.weight for factor in definition.factors},
        top_n=2,
    )

    assert definition.status == "shadow_live"
    assert definition.enabled is True
    assert definition.config["deployment_scope"] == "forward_paper_only"
    assert selections == {"20260630": ["A", "B"]}
    assert holdings["rank"].tolist() == [1, 2]


def test_unchanged_target_does_not_trigger_daily_paper_rebalance(tmp_path: Path) -> None:
    """月频策略每天更新理论曲线，但相同目标不能重复生成委托。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_strategy_instance(
        {
            "strategy_id": "quality_value_lowvol_v0",
            "name": "Quality Value LowVol V0",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": [],
            "factors": [],
            "construction": {"top_n": 20},
            "risk_overlay": "vol_20_45_to_30",
            "benchmark": "510300",
        }
    )
    from runtime.strategy_state_writer import StrategyHoldingState, write_strategy_instance_state

    write_strategy_instance_state(
        paths,
        "quality_value_lowvol_v0",
        "20260721",
        1.1,
        [StrategyHoldingState("000001.SZ", 0.5, 10.0), StrategyHoldingState("000002.SZ", 0.5, 20.0)],
    )

    assert _target_changed(paths, "quality_value_lowvol_v0", {"000001.SZ": 0.5, "000002.SZ": 0.5}) is False
    assert _target_changed(paths, "quality_value_lowvol_v0", {"000001.SZ": 0.3}) is True


def test_benchmark_history_and_increment_are_merged(tmp_path: Path) -> None:
    """510300 基准必须拼接历史与增量，且增量同日覆盖历史。"""
    history = tmp_path / "fund_history.duckdb"
    increment = tmp_path / "benchmark_increment.duckdb"
    with duckdb.connect(str(history)) as connection:
        connection.execute(
            "CREATE TABLE etf_lof_reits_daily_adj(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE, adj_factor DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO etf_lof_reits_daily_adj VALUES (?, ?, ?, ?)",
            [("510300.SH", "20260102", 4.0, 1.0), ("510300.SH", "20260105", 4.1, 1.0)],
        )
    with duckdb.connect(str(increment)) as connection:
        connection.execute("CREATE TABLE fund_daily(ts_code VARCHAR, trade_date VARCHAR, close DOUBLE)")
        connection.execute("CREATE TABLE fund_adj(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        connection.executemany(
            "INSERT INTO fund_daily VALUES (?, ?, ?)",
            [("510300.SH", "20260105", 4.2), ("510300.SH", "20260106", 4.3)],
        )
        connection.executemany(
            "INSERT INTO fund_adj VALUES (?, ?, ?)",
            [("510300.SH", "20260105", 1.0), ("510300.SH", "20260106", 1.0)],
        )

    curve = load_adjusted_fund_curve(history, increment, "510300.SH")

    assert len(curve) == 3
    assert curve.loc[pd.Timestamp("2026-01-05")] == pytest.approx(4.2 / 4.0)


def _candidate(symbol: str, report_factor: float | None, current_factor: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "raw_close": 10.0,
        "current_adj_factor": current_factor,
        "report_adj_factor": report_factor,
        "roa": 5.0,
        "ocf_to_or": 10.0,
        "eps": 1.0,
        "bps": 5.0,
        "vol60": 0.02,
    }
