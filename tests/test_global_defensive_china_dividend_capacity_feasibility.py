"""全球防守与红利低波90/10容量门禁测试。"""

from examples import global_defensive_china_dividend_capacity_feasibility_study as study


def test_weights_and_capital_are_fixed_before_returns() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert sum(study.WEIGHTS.values()) == 1.0
    assert study.WEIGHTS[study.DIVIDEND] == 0.10
    assert definition["portfolio_preview"]["capital"] == 1_000_000.0
    assert definition["portfolio_preview"]["return_backtest"] is False
    assert definition["weights_fixed_before_return_loading"] is True


def test_core_assets_each_receive_thirty_percent() -> None:
    for symbol in [
        study.core.SP500_SYMBOL,
        study.core.GOLD_SYMBOL,
        study.core.BOND_SYMBOL,
    ]:
        assert study.WEIGHTS[symbol] == 0.30
