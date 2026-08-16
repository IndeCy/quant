"""机构席位净买入固定回测研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import top_inst_flow_study as study


def test_registered_risk_scheme_activates_configurable_overlay() -> None:
    """固定阈值风险层必须使用共享研究器的GRID实现入口。"""
    assert study.RISK_SCHEME == "GRID"
    assert (
        study.RESEARCH_SPEC.definition["risk_overlay"]["implementation_scheme"]
        == study.RISK_SCHEME
    )


def test_build_targets_turns_cash_when_candidates_insufficient() -> None:
    """候选不足20只的月份必须生成空目标，而不是沿用旧持仓。"""
    rows: list[dict[str, object]] = []
    for index in range(20):
        rows.append(_candidate("20240131", index))
    for index in range(19):
        rows.append(_candidate("20240229", index))

    targets, holdings, counts = study.build_targets(
        pd.DataFrame(rows),
        ["20240131", "20240229"],
    )

    assert len(targets["20240131"]) == 20
    assert targets["20240229"] == {}
    assert len(holdings) == 20
    assert counts["latest"] == 19


def test_gate_rejects_excessive_turnover() -> None:
    """收益达标但年化换手过高时仍不得晋级。"""
    good = {
        "annualized_return": 0.12,
        "max_drawdown": -0.20,
        "sharpe": 0.80,
        "excess_return": 0.10,
        "annual_turnover": 6.0,
    }
    metrics = {key: dict(good) for key in [*study.FOLDS, "full"]}
    metrics["full"]["annual_turnover"] = 12.0

    gate = study.evaluate_gate(metrics, quality_correlation=0.2)

    assert gate["passed"] is False
    assert gate["checks"]["annual_turnover_below_10x"] is False


def test_same_fingerprint_reuses_without_full_history_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同指纹必须复用历史结果，不再回补数据或回测。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    (tmp_path / "etf_lof_reits_daily_adj_20041220_20260617.duckdb").write_bytes(
        b"fund"
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live_market_increment.duckdb").write_bytes(b"increment")
    (data_dir / "benchmark_increment.duckdb").write_bytes(b"benchmark")

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
        lambda *args, **kwargs: pytest.fail("不应回补历史或运行回测"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def _candidate(signal_date: str, index: int) -> dict[str, object]:
    """构造一个标准候选。"""
    return {
        "signal_date": signal_date,
        "symbol": f"{index:06d}.SZ",
        "name": f"股票{index}",
        "total_net_buy": float(index + 1),
        "adv_rmb": 1_000.0,
        "event_days": 1,
        "unique_seat_events": 1,
        "vol60": 0.02,
        "ret120": 0.10,
    }
