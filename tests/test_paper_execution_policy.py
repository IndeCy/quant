"""账户级Paper执行政策测试。"""

from __future__ import annotations

from runtime.paper_execution_policy import broker_config_from_instance


def test_legacy_strategy_without_policy_keeps_previous_default() -> None:
    """没有显式声明时必须返回None，防止迁移后静默改变旧账户。"""
    assert broker_config_from_instance({"config": {"initial_capital": 100_000}}) is None


def test_explicit_strategy_policy_builds_complete_broker_config() -> None:
    """策略声明应完整映射成交、费用、流动性和税费豁免口径。"""
    config = broker_config_from_instance(
        {
            "config": {
                "paper_execution_policy": {
                    "slippage_bps": 10,
                    "execution_delay": 1,
                    "max_participation_rate": 0.01,
                    "commission_rate": 0.0003,
                    "stamp_tax_rate": 0.001,
                    "min_commission": 5,
                    "lot_size": 100,
                    "open_aware_order_sizing": True,
                    "tax_exempt_symbols": ["518880.SH", "511010.SH"],
                }
            }
        }
    )

    assert config is not None
    assert config.slippage_bps == 10
    assert config.execution_delay == 1
    assert config.max_participation_rate == 0.01
    assert config.commission_rate == 0.0003
    assert config.stamp_tax_rate == 0.001
    assert config.min_commission == 5
    assert config.lot_size == 100
    assert config.open_aware_order_sizing is True
    assert config.tax_exempt_symbols == frozenset({"518880.SH", "511010.SH"})
