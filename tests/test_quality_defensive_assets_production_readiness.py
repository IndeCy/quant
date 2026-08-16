"""Quality防御组合生产就绪研究的纯规则测试。"""

from __future__ import annotations

import pytest

from examples.quality_defensive_assets_production_readiness_study import (
    blend_target_weights,
    evaluate_readiness,
)


def test_blend_target_weights_preserves_fixed_defensive_sleeves() -> None:
    """Core风险降到30%时，总暴露应为30%+70%*30%=51%。"""
    weights = blend_target_weights(
        {"000001.SZ": 0.15, "000002.SZ": 0.15},
        {"518880.SH": 0.15, "511010.SH": 0.15},
    )

    assert weights == {
        "000001.SZ": pytest.approx(0.105),
        "000002.SZ": pytest.approx(0.105),
        "518880.SH": pytest.approx(0.15),
        "511010.SH": pytest.approx(0.15),
    }
    assert sum(weights.values()) == pytest.approx(0.51)


def test_evaluate_readiness_accepts_complete_t1_dry_run() -> None:
    """数据齐全且委托进入下一交易日时才通过。"""
    result = {
        "data_as_of": "20260723",
        "increment_coverage_issues": [],
        "missing_market_symbols": [],
        "defensive_orders_present": True,
        "paper_execution_policy_persisted": True,
        "paper_target_batch_persisted": True,
        "paper_created_orders": 12,
        "paper_next_trade_date": "20260724",
    }

    assert evaluate_readiness(result) == []


def test_evaluate_readiness_reports_all_blocking_issues() -> None:
    """准入失败原因必须完整返回，便于稳定性任务报警。"""
    result = {
        "data_as_of": "20260723",
        "increment_coverage_issues": ["518880.SH.fund_adj"],
        "missing_market_symbols": ["511010.SH"],
        "defensive_orders_present": False,
        "paper_execution_policy_persisted": False,
        "paper_target_batch_persisted": False,
        "paper_created_orders": 0,
        "paper_next_trade_date": "20260723",
    }

    assert evaluate_readiness(result) == [
        "基金增量不完整",
        "目标行情不完整",
        "防守资产未生成委托",
        "账户执行参数未持久化",
        "T+1目标组合批次未持久化",
        "未生成T+1委托",
        "委托日期未顺延到下一交易日",
    ]
