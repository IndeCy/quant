"""SUE事件调仓日历可行性测试。"""

from __future__ import annotations

import pandas as pd

from examples import (
    earnings_surprise_event_schedule_feasibility_study as study,
)


def test_max_false_run_counts_consecutive_skipped_months() -> None:
    """连续空窗应按月份计数而不是总空窗数。"""
    values = pd.Series([True, False, False, True, False])

    assert study.max_false_run(values) == 2


def test_schedule_gate_accepts_two_month_holding_gap() -> None:
    """最多连续两个月沿用持仓仍属于冻结定义允许范围。"""
    base = {
        "asof_violations": 0,
        "event_age_violations": 0,
        "history_observation_violations": 0,
        "duplicate_signal_symbol": 0,
        "fold_constructible_share": {"a": 0.9, "b": 0.85},
    }
    schedule = {
        "event_month_share": 0.9,
        "max_consecutive_skipped_months": 2,
        "minimum_rebalance_months_per_full_year": 10,
        "first_rebalance_date": "20150227",
    }

    gate = study.evaluate_schedule(base, schedule)

    assert gate["passed"] is True


def test_cached_schedule_attempt_skips_data_read(monkeypatch) -> None:
    """相同事件日历指纹不得重复读取大表。"""

    class CachedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: CachedAttempt(),
    )
    monkeypatch.setattr(study, "_data_version", lambda paths: "test")
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("不应读取数据")
        ),
    )

    result = study.run_study(object(), "20260724")  # type: ignore[arg-type]

    assert result == {"reused": True}
