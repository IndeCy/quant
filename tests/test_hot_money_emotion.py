import pandas as pd

from runtime.hot_money_emotion import build_market_emotion_daily


def test_build_market_emotion_daily_counts_limit_types() -> None:
    rows = pd.DataFrame(
        [
            {"trade_date": "20260707", "ts_code": "000001.SZ", "limit_type": "U", "open_times": 0, "amount": 100.0},
            {"trade_date": "20260707", "ts_code": "000002.SZ", "limit_type": "U", "open_times": 2, "amount": 200.0},
            {"trade_date": "20260707", "ts_code": "000003.SZ", "limit_type": "D", "open_times": 0, "amount": 150.0},
            {"trade_date": "20260707", "ts_code": "000004.SZ", "limit_type": "Z", "open_times": 1, "amount": 80.0},
        ]
    )

    emotion = build_market_emotion_daily(rows)
    row = emotion.iloc[0].to_dict()

    assert row["trade_date"] == "20260707"
    assert row["limit_up_count"] == 2
    assert row["limit_down_count"] == 1
    assert row["zha_ban_count"] == 1
    assert row["open_board_rate"] == 0.5
    assert row["limit_amount"] == 530.0


def test_build_market_emotion_daily_merges_market_amount_change() -> None:
    rows = pd.DataFrame(
        [
            {"trade_date": "20260706", "ts_code": "000001.SZ", "limit_type": "U", "open_times": 0, "amount": 100.0},
            {"trade_date": "20260707", "ts_code": "000002.SZ", "limit_type": "D", "open_times": 0, "amount": 200.0},
        ]
    )
    market_amount = pd.DataFrame(
        [
            {"trade_date": "20260706", "market_amount": 1000.0},
            {"trade_date": "20260707", "market_amount": 1200.0},
        ]
    )

    emotion = build_market_emotion_daily(rows, market_amount)

    assert emotion.iloc[1]["market_amount"] == 1200.0
    assert round(float(emotion.iloc[1]["market_amount_chg"]), 4) == 0.2
