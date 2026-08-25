"""机构席位净买入数据门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import top_inst_flow_feasibility_study as study


def _diagnostics() -> dict[str, float]:
    """返回通过源数据质量门槛的诊断夹具。"""
    return {
        "checked_trade_day_share": 1.0,
        "successful_trade_day_share": 1.0,
        "empty_trade_day_share": 0.0,
        "max_raw_rows": 500.0,
        "raw_rows": 10_000.0,
        "normalized_rows": 5_000.0,
        "deduplicated_row_share": 0.5,
        "duplicate_event_keys": 0.0,
        "net_buy_identity_violations": 0.0,
        "source_rows_represented": 10_000.0,
        "stored_unique_events": 5_000.0,
        "visibility_violations": 0.0,
    }


def test_feasibility_rejects_sparse_locked_months() -> None:
    """最近阶段候选不足时不得被早期覆盖掩盖。"""
    dates = pd.date_range("2024-01-31", periods=24, freq="ME")
    monthly = pd.DataFrame(
        {
            "signal_date": dates.strftime("%Y%m%d"),
            "candidate_count": [150] * 12 + [50] * 12,
            "unique_factor_values": [140] * 12 + [45] * 12,
            "top20_count": [20] * 24,
            "top20_median_adv_rmb": [50_000_000.0] * 24,
            "top20_tradable_share": [1.0] * 24,
            "top20_median_event_days": [3.0] * 24,
            "spearman_amount20": [0.0] * 24,
            "spearman_vol60": [0.0] * 24,
            "spearman_ret120": [0.0] * 24,
        }
    )

    result = study.evaluate_feasibility(
        monthly,
        {"p01": 0.01, "median": 0.1, "p99": 1.0},
        _diagnostics(),
        "20251231",
        {},
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_monthly_coverage_keeps_missing_month() -> None:
    """无候选月份必须显式记零，不能从覆盖率分母消失。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"],
            "net_buy_to_adv": [0.2],
            "factor_score": [1.0],
            "adv_rmb": [50_000_000.0],
            "event_days": [2],
            "vol60": [0.02],
            "ret120": [0.10],
        }
    )

    monthly = study.build_monthly_coverage(
        candidates,
        ["20240131", "20240229"],
    )

    assert monthly["candidate_count"].tolist() == [1, 0]
    assert monthly["top20_count"].tolist() == [1, 0]


def test_same_fingerprint_reuses_without_api_or_market_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同指纹必须复用结论，不再扫描行情或调用远端。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"increment")

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
        lambda *args, **kwargs: pytest.fail("不应调用行情或远端"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
