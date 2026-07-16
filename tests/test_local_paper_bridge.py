"""策略目标组合到本地 Paper Broker 桥接测试。"""

import pandas as pd

from runtime.local_paper_bridge import market_data_from_bars


def test_market_data_from_bars_preserves_execution_constraints() -> None:
    """统一行情转换不能覆盖策略数据携带的停牌和涨跌停标记。"""
    bars = {
        "000001.SZ": pd.DataFrame(
            [
                {
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 0.0,
                    "amount": 0.0,
                    "is_suspended": True,
                    "limit_up": True,
                    "limit_down": False,
                }
            ],
            index=pd.to_datetime(["2026-07-15"]),
        )
    }

    frame = market_data_from_bars(bars, "20260715")

    assert bool(frame.iloc[0]["is_suspended"]) is True
    assert bool(frame.iloc[0]["limit_up"]) is True
    assert bool(frame.iloc[0]["limit_down"]) is False
