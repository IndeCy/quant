import pandas as pd
import pytest

from examples.quality_volatility_grid_search import add_calmar


def test_add_calmar_uses_annual_return_over_absolute_drawdown():
    metrics = pd.DataFrame({"年化收益": [0.12], "最大回撤": [-0.30]})

    result = add_calmar(metrics)

    assert result["Calmar"].iloc[0] == pytest.approx(0.4)
