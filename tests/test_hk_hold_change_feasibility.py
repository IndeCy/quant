"""北向持仓占比增加数据门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import hk_hold_change_feasibility_study as study


def _diagnostics() -> dict[str, float]:
    """返回通过基础数据质量门槛的诊断夹具。"""
    return {
        "visibility_violations": 0,
        "duplicate_signal_symbol_rows": 0,
        "ratio_range_violations": 0,
        "gap_violations": 0,
        "checked_snapshot_share": 1.0,
        "nonempty_snapshot_share": 1.0,
        "minimum_nonempty_snapshot_rows": 900,
        "latest_snapshot_rows": 900,
    }


def test_feasibility_rejects_sparse_locked_months() -> None:
    """最近阶段候选不足时，不得被历史高覆盖掩盖。"""
    dates = pd.date_range("2023-01-31", periods=24, freq="ME")
    monthly = pd.DataFrame(
        {
            "signal_date": dates.strftime("%Y%m%d"),
            "candidate_count": [400] * 12 + [100] * 12,
            "unique_factor_values": [350] * 12 + [90] * 12,
            "top40_count": [40] * 24,
            "top40_median_adv_rmb": [20_000_000.0] * 24,
            "top40_tradable_share": [1.0] * 24,
            "spearman_amount20": [0.0] * 24,
            "spearman_vol60": [0.0] * 24,
            "spearman_ret120": [0.0] * 24,
        }
    )

    result = study.evaluate_feasibility(
        monthly,
        {"p01": 0.01, "median": 0.10, "p99": 1.0},
        _diagnostics(),
        "20241231",
        {},
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_monthly_coverage_keeps_missing_month_as_zero() -> None:
    """预期月份无快照时必须显式记零，不能从统计中消失。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"],
            "holding_ratio_change": [0.2],
            "factor_score": [1.0],
            "adv_rmb": [20_000_000.0],
            "vol60": [0.02],
            "ret120": [0.10],
        }
    )

    monthly = study.build_monthly_coverage(
        candidates,
        ["20240131", "20240229"],
    )

    assert monthly["candidate_count"].tolist() == [1, 0]
    assert monthly["top40_count"].tolist() == [1, 0]


def test_feasibility_reuses_fingerprint_without_api_or_market_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同研究指纹应复用结论，不再调用远端接口或扫描行情。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"fixture")
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
        lambda *args, **kwargs: pytest.fail("不应访问行情或远端接口"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
