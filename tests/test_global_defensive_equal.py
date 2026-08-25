"""全球防守三资产等权研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data.fund_portfolio import FundPortfolioPanel
from examples import global_defensive_equal_feasibility_study as study


def _panel() -> FundPortfolioPanel:
    dates = pd.bdate_range("2014-01-01", "2015-03-31")
    rows: list[dict[str, object]] = []
    close: dict[str, pd.Series] = {}
    for offset, symbol in enumerate(study.ASSETS):
        values = pd.Series(
            1.0 + offset + pd.RangeIndex(len(dates)) * 0.001,
            index=dates,
            dtype=float,
        )
        close[symbol] = values
        for date, value in values.items():
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": value,
                    "high": value,
                    "low": value,
                    "close": value,
                    "volume": 1_000_000.0,
                    "amount": 20_000.0,
                    "adj_factor": 1.0,
                }
            )
    bars = pd.DataFrame(rows).set_index(["date", "symbol"])
    coverage = [
        {
            "symbol": symbol,
            "start_date": "20140101",
            "end_date": "20150331",
            "row_count": len(dates),
        }
        for symbol in study.ASSETS
    ]
    return FundPortfolioPanel(
        bars=bars,
        adjusted_close=pd.DataFrame(close),
        calendar=list(dates),
        coverage=coverage,
        latest_common_date="20150331",
    )


def test_monthly_liquidity_keeps_all_three_assets() -> None:
    """每个共同月末必须保留三只资产并统一金额单位。"""
    panel = _panel()
    monthly = study.build_monthly_liquidity(panel)

    assert monthly.groupby("signal_date")["symbol"].nunique().eq(3).all()
    assert monthly["amount_rmb"].eq(20_000_000.0).all()
    assert monthly["signal_date"].nunique() == len(
        [
            date
            for date in study.month_end_signal_dates(panel.calendar)
            if date >= pd.Timestamp(study.STUDY_START)
        ]
    )


def test_feasibility_passes_complete_liquid_panel() -> None:
    """覆盖、流动性和价格完整时应允许固定回测。"""
    panel = _panel()
    result = study.evaluate_feasibility(
        panel,
        study.build_monthly_liquidity(panel),
        "20150405",
    )

    assert result["passed"] is True
    assert result["decision"] == "CONTINUE_TO_FIXED_MULTIFOLD_BACKTEST"
    assert result["constructible_months"] <= result["signal_months"]


def test_feasibility_rejects_stale_data() -> None:
    """共同截止日期过旧时不得用历史回测掩盖数据问题。"""
    panel = _panel()
    result = study.evaluate_feasibility(
        panel,
        study.build_monthly_liquidity(panel),
        "20150501",
    )

    assert result["checks"]["data_is_fresh"] is False
    assert result["passed"] is False


def test_same_fingerprint_reuses_without_fund_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相同运行指纹复用时不得读取基金大表。"""
    for relative in [
        "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
        "data/benchmark_increment.duckdb",
    ]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")

    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应扫描基金行情"),
    )

    result = study.run_study(
        study.RuntimePaths(tmp_path),
        "20260724",
    )

    assert result["reused"] is True
