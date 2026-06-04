"""
测试产业链选股策略
"""

import unittest

import pandas as pd

from backtest.chain_selection import (
    ChainDefinition,
    ChainStock,
    ChainStockSelectionStrategy,
)


def make_bars(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """根据收盘价构造最小 OHLCV 数据。"""
    dates = pd.date_range(start="2024-01-01", periods=len(closes), freq="D")
    volume_values = volumes or [1000000] * len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [price + 1 for price in closes],
            "low": [price - 1 for price in closes],
            "close": closes,
            "volume": volume_values,
        },
        index=dates,
    )


class TestChainStockSelectionStrategy(unittest.TestCase):
    """验证产业链选股的三种模式。"""

    def setUp(self):
        self.chains = [
            ChainDefinition(
                name="半导体",
                proxy_symbol="半导体链",
                stocks=[
                    ChainStock("A设备", "设备龙头", "半导体", "设备"),
                    ChainStock("A设计", "设计龙头", "半导体", "设计"),
                ],
            ),
            ChainDefinition(
                name="汽车",
                proxy_symbol="汽车链",
                stocks=[
                    ChainStock("B整车", "整车龙头", "汽车", "整车"),
                    ChainStock("B零部件", "零部件龙头", "汽车", "零部件"),
                ],
            ),
        ]

    def test_single_chain_selects_only_target_chain_stocks(self):
        """A方案只应在指定产业链内部选择强势个股。"""
        strategy = ChainStockSelectionStrategy(
            chains=self.chains,
            mode="single_chain",
            target_chain="半导体",
            top_n=1,
            rebalance_frequency=5,
            momentum_windows=[2],
        )
        data = {
            "A设备": make_bars([10, 11, 13]),
            "A设计": make_bars([10, 10, 10.5]),
            "B整车": make_bars([10, 10, 20]),
            "B零部件": make_bars([10, 10, 19]),
        }

        signals = strategy.generate_signals(data, data["A设备"].index[-1])

        self.assertEqual(signals, {"A设备": 1.0, "A设计": 0.0})

    def test_multi_chain_selects_stock_from_strongest_chain(self):
        """B方案应先选择强势产业链，再在链内选择强势个股。"""
        strategy = ChainStockSelectionStrategy(
            chains=self.chains,
            mode="multi_chain",
            top_n=1,
            rebalance_frequency=5,
            momentum_windows=[2],
            chain_momentum_window=2,
        )
        data = {
            "半导体链": make_bars([10, 10, 11]),
            "汽车链": make_bars([10, 12, 16]),
            "A设备": make_bars([10, 11, 15]),
            "A设计": make_bars([10, 10, 13]),
            "B整车": make_bars([10, 10, 15]),
            "B零部件": make_bars([10, 10, 14]),
        }

        signals = strategy.generate_signals(data, data["半导体链"].index[-1])

        self.assertEqual(signals, {"B整车": 1.0, "B零部件": 0.0})

    def test_whole_pool_ignores_chain_and_selects_strongest_stocks(self):
        """C方案应忽略产业链分组，从全池直接选择最强个股。"""
        strategy = ChainStockSelectionStrategy(
            chains=self.chains,
            mode="whole_pool",
            top_n=2,
            rebalance_frequency=5,
            momentum_windows=[2],
        )
        data = {
            "A设备": make_bars([10, 10, 14]),
            "A设计": make_bars([10, 10, 10.2]),
            "B整车": make_bars([10, 10, 15]),
            "B零部件": make_bars([10, 10, 11]),
        }

        signals = strategy.generate_signals(data, data["A设备"].index[-1])

        self.assertEqual(
            signals,
            {"A设备": 0.5, "A设计": 0.0, "B整车": 0.5, "B零部件": 0.0},
        )

    def test_chain_gate_blocks_weak_target_chain(self):
        """产业链代理弱于基线趋势时，A方案应清空目标链持仓。"""
        strategy = ChainStockSelectionStrategy(
            chains=self.chains,
            mode="single_chain",
            target_chain="半导体",
            top_n=1,
            rebalance_frequency=5,
            momentum_windows=[2],
            chain_gate_symbol="市场基线",
            chain_momentum_window=2,
        )
        data = {
            "市场基线": make_bars([10, 10, 12]),
            "半导体链": make_bars([10, 10, 9]),
            "A设备": make_bars([10, 11, 13]),
            "A设计": make_bars([10, 10, 10.5]),
        }

        signals = strategy.generate_signals(data, data["A设备"].index[-1])

        self.assertEqual(signals, {"A设备": 0.0, "A设计": 0.0})


if __name__ == "__main__":
    unittest.main()
