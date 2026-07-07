import pandas as pd

from runtime.hot_money_state import MarketState, MarketStateEngine


def test_market_state_engine_classifies_distribution_on_extreme_risk() -> None:
    emotion = pd.DataFrame(
        [
            {
                "trade_date": "20260701",
                "limit_up_count": 80,
                "limit_down_count": 2,
                "zha_ban_count": 3,
                "open_board_rate": 0.1,
                "market_amount_chg": 0.1,
            },
            {
                "trade_date": "20260702",
                "limit_up_count": 20,
                "limit_down_count": 40,
                "zha_ban_count": 30,
                "open_board_rate": 1.2,
                "market_amount_chg": -0.2,
            },
        ]
    )

    result = MarketStateEngine().classify_series(emotion)

    assert result.iloc[-1]["raw_state"] == MarketState.DISTRIBUTION.value
    assert result.iloc[-1]["smoothed_state"] == MarketState.DISTRIBUTION.value
    assert "极端风险" in result.iloc[-1]["transition_reason"]


def test_market_state_engine_prevents_single_day_ice_to_bubble_jump() -> None:
    emotion = pd.DataFrame(
        [
            {
                "trade_date": "20260701",
                "limit_up_count": 5,
                "limit_down_count": 30,
                "zha_ban_count": 10,
                "open_board_rate": 2.0,
                "market_amount_chg": -0.1,
            },
            {
                "trade_date": "20260702",
                "limit_up_count": 90,
                "limit_down_count": 1,
                "zha_ban_count": 2,
                "open_board_rate": 0.02,
                "market_amount_chg": 0.2,
            },
        ]
    )

    result = MarketStateEngine().classify_series(emotion)

    assert result.iloc[0]["smoothed_state"] == MarketState.ICE_COLD.value
    assert result.iloc[1]["raw_state"] == MarketState.BUBBLE.value
    assert result.iloc[1]["smoothed_state"] in {MarketState.REBOUND.value, MarketState.EXPANSION.value}
