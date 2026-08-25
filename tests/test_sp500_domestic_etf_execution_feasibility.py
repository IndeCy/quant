"""境内标普500 ETF当前执行可行性测试。"""

import pandas as pd

from examples import sp500_domestic_etf_execution_feasibility_study as study


def test_definition_uses_same_execution_thresholds_as_nasdaq_scan() -> None:
    gate = study.RESEARCH_SPEC.definition["frozen_gate"]
    source_gate = study.support.RESEARCH_SPEC.definition["frozen_gate"]

    assert gate == source_gate
    assert (
        study.RESEARCH_SPEC.definition[
            "does_not_authorize_instrument_substitution"
        ]
        is True
    )


def test_universe_requires_pure_sp500_etf() -> None:
    basic = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D"],
            "name": ["标普500ETF", "标普500ETF联接", "标普科技ETF", "纳指ETF"],
            "benchmark": [
                "标普500指数",
                "标普500指数",
                "标普科技指数",
                "纳斯达克100指数",
            ],
            "list_date": ["20200101"] * 4,
        }
    )

    selected = study.select_sp500_etfs(basic)

    assert selected["ts_code"].tolist() == ["A"]
