from __future__ import annotations

import pandas as pd

from examples import limit_up_first_board_execution_audit as audit


def test_definition_is_audit_only_and_does_not_load_returns() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["return_outcomes_loaded"] is False
    assert definition["promotion_scope"] == "audit_only_no_strategy_registration"


def test_attach_execution_dates_uses_next_trading_day() -> None:
    selected = pd.DataFrame(
        [
            {"trade_date": "20230106", "ts_code": "000001.SZ"},
            {"trade_date": "20230109", "ts_code": "000002.SZ"},
        ]
    )

    pairs = audit.attach_execution_dates(
        selected,
        ["20230106", "20230109", "20230110"],
    )

    assert pairs["execution_date"].tolist() == ["20230109", "20230110"]


def test_classify_distinguishes_intraday_touch_from_open_limit() -> None:
    rows = pd.DataFrame(
        [
            {
                "signal_date": "20230106",
                "execution_date": "20230109",
                "ts_code": "000001.SZ",
                "open": 10.50,
                "high": 11.00,
                "pre_close": 10.00,
                "st_name": "",
            },
            {
                "signal_date": "20230106",
                "execution_date": "20230109",
                "ts_code": "000002.SZ",
                "open": 11.00,
                "high": 11.00,
                "pre_close": 10.00,
                "st_name": "",
            },
        ]
    )

    classified = audit.classify_buy_blocks(rows)

    assert classified["current_model_blocks"].tolist() == [True, True]
    assert classified["open_rule_blocks"].tolist() == [False, True]
    assert classified["false_block"].tolist() == [True, False]
