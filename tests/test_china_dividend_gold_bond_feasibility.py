"""国内红利低波黄金国债数据门禁测试。"""

from examples import china_dividend_gold_bond_feasibility_study as study


def test_definition_is_feasibility_only_and_fixed_equal_weight() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["portfolio_preview"]["return_backtest"] is False
    assert definition["portfolio_preview"]["weights"] == {
        symbol: 1 / 3 for symbol in study.SYMBOLS
    }
    assert definition["decision"] == "feasibility_only_no_return_backtest"


def test_universe_has_domestic_equity_gold_and_bond() -> None:
    assert set(study.SYMBOLS) == {
        study.source.DIVIDEND,
        study.source.GOLD,
        study.source.BOND,
    }
