"""低隔夜跳空风险点时特征与门禁测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from data.overnight_gap_risk import materialize_overnight_gap_risk
from examples import overnight_gap_risk_feasibility_study as study
from factors.overnight_gap_risk import score_overnight_gap_risk


def test_materialization_does_not_use_future_gap() -> None:
    """未来极端跳空不得改写较早日期的60日特征。"""
    connection = duckdb.connect()
    frame = pd.DataFrame(
        {
            "ts_code": ["A"] * 5,
            "trade_date": [f"2024010{i}" for i in range(1, 6)],
            "open_qfq": [10.0, 10.1, 9.9, 10.2, 50.0],
            "pre_close_qfq": [10.0] * 5,
        }
    )
    connection.register("source", frame)
    connection.execute(
        "CREATE TABLE daily_adj_cache AS SELECT * FROM source"
    )
    materialize_overnight_gap_risk(
        connection,
        window=3,
        minimum_observations=3,
    )
    before = connection.execute(
        """
        SELECT overnight_volatility
        FROM overnight_gap_risk_features
        WHERE trade_date='20240103'
        """
    ).fetchone()[0]
    connection.execute(
        "UPDATE daily_adj_cache SET open_qfq=999 WHERE trade_date='20240105'"
    )
    materialize_overnight_gap_risk(
        connection,
        window=3,
        minimum_observations=3,
    )
    after = connection.execute(
        """
        SELECT overnight_volatility
        FROM overnight_gap_risk_features
        WHERE trade_date='20240103'
        """
    ).fetchone()[0]

    assert before == after


def test_lower_overnight_volatility_receives_higher_score() -> None:
    """隔夜波动更低的股票必须得分更高。"""
    scored = score_overnight_gap_risk(
        pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "overnight_volatility": [0.01, 0.03, 0.02],
            }
        )
    ).set_index("symbol")

    assert scored.loc["A", "factor_score"] > scored.loc["C", "factor_score"]
    assert scored.loc["C", "factor_score"] > scored.loc["B", "factor_score"]


def test_same_fingerprint_reuses_without_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同运行指纹必须复用且不扫描行情。"""
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
