"""12-1月中期动量数据与门禁测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from data.intermediate_momentum import materialize_intermediate_momentum
from examples import intermediate_momentum_feasibility_study as study
from factors.intermediate_momentum import score_intermediate_momentum


def test_materialization_skips_most_recent_period() -> None:
    """因子必须使用lag20和lag252价格，不得包含当日收益。"""
    connection = duckdb.connect()
    rows = pd.DataFrame(
        {
            "ts_code": ["A"] * 5,
            "trade_date": [f"2024010{value}" for value in range(1, 6)],
            "close_qfq": [10.0, 11.0, 12.0, 13.0, 99.0],
        }
    )
    connection.register("source", rows)
    connection.execute(
        "CREATE TABLE daily_adj_cache AS SELECT * FROM source"
    )
    materialize_intermediate_momentum(
        connection,
        formation_lag=3,
        skip_lag=1,
        source_start="20240101",
        research_start="20240101",
    )
    value = connection.execute(
        """
        SELECT intermediate_momentum
        FROM intermediate_momentum_features
        WHERE trade_date='20240105'
        """
    ).fetchone()[0]

    assert value == 13.0 / 11.0 - 1


def test_higher_intermediate_return_receives_higher_score() -> None:
    """历史收益更高的股票必须获得更高分。"""
    scored = score_intermediate_momentum(
        pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "intermediate_momentum": [-0.1, 0.3, 0.1],
            }
        )
    ).set_index("symbol")

    assert scored.loc["B", "factor_score"] > scored.loc["C", "factor_score"]
    assert scored.loc["C", "factor_score"] > scored.loc["A", "factor_score"]


def test_same_fingerprint_reuses_without_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同运行指纹复用时不得再次扫描行情。"""
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
            AssertionError("不应扫描行情")
        ),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result == {"reused": True}
