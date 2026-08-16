"""官方源净流入数据门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import source_net_moneyflow_feasibility_study as study


def _diagnostics() -> dict[str, float]:
    return {
        "checked_trade_day_share": 1.0,
        "successful_trade_day_share": 1.0,
        "max_raw_rows": 5_000.0,
        "duplicate_daily_rows": 0.0,
        "symmetric_bucket_share": 1.0,
        "turnover_ratio_p01": 1.95,
        "turnover_ratio_median": 2.0,
        "turnover_ratio_p99": 2.05,
        "visibility_violations": 0.0,
        "source_share_range_violations": 0.0,
    }


def test_feasibility_rejects_broken_symmetric_source_contract() -> None:
    """分类金额不再双边对称时，既有归一化口径必须失效。"""
    dates = pd.date_range("2024-01-31", periods=24, freq="ME")
    monthly = pd.DataFrame(
        {
            "signal_date": dates.strftime("%Y%m%d"),
            "candidate_count": [1_500] * 24,
            "unique_factor_values": [1_400] * 24,
            "top40_count": [40] * 24,
            "top40_median_adv_rmb": [50_000_000.0] * 24,
            "top40_tradable_share": [1.0] * 24,
            "spearman_amount20": [0.0] * 24,
            "spearman_vol60": [0.0] * 24,
            "spearman_ret20": [0.0] * 24,
            "spearman_ret120": [0.0] * 24,
            "spearman_signed_amount": [0.1] * 24,
        }
    )
    diagnostics = _diagnostics()
    diagnostics["symmetric_bucket_share"] = 0.8

    result = study.evaluate_feasibility(
        monthly,
        {"p01": 0.01, "median": 0.1, "p99": 0.3},
        diagnostics,
        "20251231",
        {},
    )

    assert result["passed"] is False
    assert result["checks"]["symmetric_bucket_contract"] is False


def test_monthly_coverage_keeps_missing_month() -> None:
    """空月必须留在覆盖率分母。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"],
            "source_net_turnover_share": [0.1],
            "factor_score": [1.0],
            "adv_rmb": [50_000_000.0],
            "vol60": [0.02],
            "ret20": [0.05],
            "ret120": [0.10],
            "signed_amount_pressure": [0.02],
        }
    )

    monthly = study.build_monthly_coverage(
        candidates,
        ["20240131", "20240229"],
    )

    assert monthly["candidate_count"].tolist() == [1, 0]


def test_same_fingerprint_reuses_without_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同V2指纹必须直接复用。"""
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
        lambda *args, **kwargs: pytest.fail("不应扫描数据"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
