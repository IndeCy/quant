"""全市场宽度与流动性指标测试。"""

from __future__ import annotations

import pandas as pd

from runtime.market_breadth_liquidity import build_breadth_liquidity_frame


def test_build_breadth_liquidity_frame_from_daily_bars() -> None:
    """全A日线应能沉淀上涨下跌、等权收益、成交额和均线宽度。"""
    rows = []
    for index, trade_date in enumerate(["20260707", "20260708", "20260709", "20260710"]):
        rows.extend(
            [
                {"trade_date": trade_date, "ts_code": "AAA.SZ", "close": 10 + index, "pre_close": 9 + index, "vol": 100, "amount": 1000 + index},
                {"trade_date": trade_date, "ts_code": "BBB.SZ", "close": 10 - index, "pre_close": 11 - index, "vol": 0, "amount": 100 + index},
                {"trade_date": trade_date, "ts_code": "CCC.SZ", "close": 8, "pre_close": 8, "vol": 50, "amount": 500 + index},
            ]
        )

    frame = build_breadth_liquidity_frame(pd.DataFrame(rows), ma_windows=(2, 3), high_low_window=3)
    latest = frame.iloc[-1]

    assert latest["breadth_up_count"] == 1
    assert latest["breadth_down_count"] == 1
    assert latest["breadth_flat_count"] == 1
    assert latest["market_amount"] == 1609
    assert latest["zero_volume_ratio"] == 1 / 3
    assert 0 <= latest["ma2_above_ratio"] <= 1
    assert "new_high_20_count" in frame.columns
