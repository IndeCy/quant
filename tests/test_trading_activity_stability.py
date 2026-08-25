"""交易活跃度稳定性因子与研究门禁测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from data.trading_activity_stability import (
    materialize_trading_activity_stability,
)
from examples import trading_activity_stability_feasibility_study as study
from factors.trading_activity_stability import (
    score_trading_activity_stability,
)


def test_materialization_uses_only_current_and_prior_amount() -> None:
    """未来成交额变化不得改写较早日期的因子。"""
    connection = duckdb.connect()
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 5,
            "trade_date": [f"2024010{day}" for day in range(1, 6)],
            "amount": [100.0, 110.0, 90.0, 105.0, 10_000.0],
        }
    )
    connection.register("daily_source", frame)
    connection.execute("CREATE TABLE daily AS SELECT * FROM daily_source")
    materialize_trading_activity_stability(
        connection,
        window=3,
        minimum_observations=3,
    )
    before = connection.execute(
        """
        SELECT activity_volatility
        FROM trading_activity_stability_features
        WHERE trade_date='20240103'
        """
    ).fetchone()[0]
    connection.execute(
        "UPDATE daily SET amount=999999 WHERE trade_date='20240105'"
    )
    materialize_trading_activity_stability(
        connection,
        window=3,
        minimum_observations=3,
    )
    after = connection.execute(
        """
        SELECT activity_volatility
        FROM trading_activity_stability_features
        WHERE trade_date='20240103'
        """
    ).fetchone()[0]

    assert before == after


def test_lower_activity_volatility_receives_higher_score() -> None:
    """成交额路径更稳定的股票必须获得更高分。"""
    scored = score_trading_activity_stability(
        pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "activity_volatility": [0.1, 0.3, 0.2],
            }
        )
    ).set_index("symbol")

    assert scored.loc["A", "factor_score"] > scored.loc["C", "factor_score"]
    assert scored.loc["C", "factor_score"] > scored.loc["B", "factor_score"]


def test_same_fingerprint_reuses_without_market_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同运行指纹必须跳过行情扫描。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"increment")

    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("不应扫描市场数据")
        ),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result == {"reused": True}
