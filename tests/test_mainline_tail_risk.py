"""主线链动尾部风险指标测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from examples.mainline_tail_risk_metrics import (
    build_drawdown_episodes,
    build_tail_profile,
    evaluate_tail_gate,
)


def test_drawdown_episode_tracks_recovery_from_original_peak() -> None:
    """回撤必须在收复原高点时结束，而不是反弹一点就结束。"""
    nav = pd.Series(
        [1.0, 0.95, 0.85, 0.90, 1.01],
        index=pd.bdate_range("2024-01-01", periods=5),
    )

    episodes = build_drawdown_episodes(nav, threshold=-0.10)

    assert len(episodes) == 1
    assert episodes[0]["trough_drawdown"] == pytest.approx(-0.15)
    assert episodes[0]["recovered"] is True
    assert episodes[0]["underwater_days"] == 4
    assert episodes[0]["recovery_days"] == 2


def test_unrecovered_episode_is_marked_censored() -> None:
    """截止日仍未收复前高时不得伪造恢复日期。"""
    nav = pd.Series(
        [1.0, 0.8, 0.85],
        index=pd.bdate_range("2024-01-01", periods=3),
    )

    episode = build_drawdown_episodes(nav, threshold=-0.10)[0]

    assert episode["recovered"] is False
    assert episode["recovery_date"] == ""


def test_tail_gate_rejects_concentrated_unreliable_profile() -> None:
    """依赖少数大涨日且回撤过深时必须拒绝长期观察资格。"""
    nav = pd.Series(
        [1.0, 1.5, 0.9, 0.95, 1.0],
        index=pd.bdate_range("2024-01-01", periods=5),
    )
    profile = build_tail_profile(nav, episode_threshold=-0.10)

    gate = evaluate_tail_gate(profile)

    assert gate["passed"] is False
    assert gate["checks"]["max_drawdown_within_35pct"] is False


def test_tail_gate_uses_total_underwater_period() -> None:
    """一年恢复门槛必须从前高起算，不能只计算谷底后的反弹期。"""
    profile = {
        "max_drawdown": -0.20,
        "maximum_underwater_days": 300,
        "top10_positive_log_contribution": 0.20,
        "annualized_return_without_best_10_days": 0.05,
        "expected_shortfall_95": -0.03,
        "positive_year_share": 0.80,
    }

    gate = evaluate_tail_gate(profile)

    assert gate["passed"] is False
    assert gate["checks"]["underwater_period_within_252_days"] is False
