"""半导体黄金国债数据门禁测试。"""

from examples import china_semiconductor_gold_bond_feasibility_study as study


def test_definition_is_fixed_equal_and_feasibility_only() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["portfolio_preview"]["weights"] == {
        symbol: 1 / 3 for symbol in study.SYMBOLS
    }
    assert definition["portfolio_preview"]["return_backtest"] is False
    assert definition["decision"] == "feasibility_only_no_return_backtest"


def test_assets_cover_growth_real_and_rate_risk() -> None:
    assert set(study.SYMBOLS) == {
        study.SEMICONDUCTOR,
        study.GOLD,
        study.BOND,
    }
