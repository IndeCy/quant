"""
Milestone 1.2 组合构建与换手压缩测试。
"""

import unittest

from backtest.portfolio_construction import CoreSatelliteTurnoverConstructor


class TestCoreSatelliteTurnoverConstructor(unittest.TestCase):
    """验证持仓惯性、换仓缓冲和换手约束。"""

    def test_keeps_previous_holding_inside_rank_band(self):
        symbols = [f"S{i:02d}" for i in range(60)]
        constructor = CoreSatelliteTurnoverConstructor(symbols, top_n=20, rank_band=40)
        previous = {symbol: 0.05 for symbol in symbols[:20]}
        ranked = symbols[20:40] + symbols[:20] + symbols[40:]

        result = constructor.build(ranked, previous)

        self.assertGreaterEqual(len(result.retained_holdings), 12)
        self.assertLessEqual(result.replacements, 8)
        self.assertLessEqual(result.turnover, 0.40)

    def test_core_satellite_weights_allocate_70_30(self):
        symbols = [f"S{i:02d}" for i in range(60)]
        constructor = CoreSatelliteTurnoverConstructor(symbols, top_n=20, rank_band=40)
        previous = {symbol: 0.05 for symbol in symbols[:20]}
        ranked = symbols[:12] + symbols[20:48] + symbols[12:20] + symbols[48:]

        result = constructor.build(ranked, previous)

        core_weight = sum(result.target_weights[symbol] for symbol in result.retained_holdings)
        satellite_weight = sum(result.target_weights[symbol] for symbol in result.satellite_holdings)
        self.assertAlmostEqual(core_weight, 0.70)
        self.assertAlmostEqual(satellite_weight, 0.30)

    def test_first_rebalance_uses_plain_equal_weight(self):
        symbols = [f"S{i:02d}" for i in range(30)]
        constructor = CoreSatelliteTurnoverConstructor(symbols, top_n=20, rank_band=40)

        result = constructor.build(symbols, previous_weights={})

        self.assertEqual(len(result.target_holdings), 20)
        self.assertAlmostEqual(result.target_weights["S00"], 0.05)


if __name__ == "__main__":
    unittest.main()
