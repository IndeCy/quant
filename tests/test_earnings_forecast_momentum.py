"""业绩预告确定性动量研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.forecast_events import (
    ForecastEventPaths,
    attach_forecast_database,
    create_forecast_signal_date_table,
    load_forecast_event_snapshot,
    materialize_forecast_event_asof,
)
from examples import earnings_forecast_momentum_study as study
from factors.earnings_forecast import score_earnings_forecast_frame


def _create_forecast_db(path: Path) -> None:
    """创建包含过去、未来和过期事件的最小预告库。"""
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE default_table (
            ts_code VARCHAR,
            end_date VARCHAR,
            ann_date VARCHAR,
            first_ann_date VARCHAR,
            type VARCHAR,
            p_change_min DOUBLE,
            p_change_max DOUBLE,
            net_profit_min DOUBLE,
            net_profit_max DOUBLE,
            last_parent_net DOUBLE,
            summary VARCHAR,
            change_reason VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO default_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("000001.SZ", "20191231", "20200115", "20200115", "预增", 20, 40, 1, 2, 1, "", ""),
            ("000001.SZ", "20200331", "20200210", "20200210", "预增", 50, 70, 2, 3, 1, "", ""),
            ("000002.SZ", "20190930", "20190901", "20190901", "续盈", 10, 20, 1, 2, 1, "", ""),
        ],
    )
    connection.close()


def test_forecast_event_asof_blocks_future_and_expired_events(tmp_path: Path) -> None:
    """信号日只能看到90日内已经公告的预告。"""
    database = tmp_path / "forecast.duckdb"
    _create_forecast_db(database)
    connection = duckdb.connect()
    try:
        create_forecast_signal_date_table(connection, ["20200131"])
        attach_forecast_database(connection, ForecastEventPaths(database))
        materialize_forecast_event_asof(connection, lookback_days=90)
        snapshot = load_forecast_event_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["symbol"].tolist() == ["000001.SZ"]
    assert snapshot.iloc[0]["publish_date"] == "20200115"
    assert snapshot.iloc[0]["report_period"] == "20191231"


def test_forecast_event_asof_rejects_invalid_window(tmp_path: Path) -> None:
    """回看窗口必须为正数。"""
    connection = duckdb.connect()
    try:
        with pytest.raises(ValueError, match="lookback_days"):
            materialize_forecast_event_asof(connection, lookback_days=0)
    finally:
        connection.close()


def test_forecast_factor_filters_uncertain_and_low_base_types() -> None:
    """因子只保留方向确定的预增、略增和续盈。"""
    frame = pd.DataFrame(
        [
            _factor_row("A", "预增", 20, 40),
            _factor_row("B", "扭亏", 300, 500),
            _factor_row("C", "略增", -10, 30),
            _factor_row("D", "续盈", 10, 20),
        ]
    )

    result = score_earnings_forecast_frame(frame)

    assert set(result["symbol"]) == {"A", "D"}
    assert result.iloc[0]["symbol"] == "A"
    assert result["factor_score"].notna().all()


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """命中研究指纹时不能读取行情并重新回测。"""
    forecast = tmp_path / "forecast.duckdb"
    forecast.write_bytes(b"test")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study.STRATEGY_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )
    paths = study.RuntimePaths(tmp_path)

    result = study.run_study(paths, "20260723")

    assert result["reused"] is True


def test_fixed_gate_rejects_high_drawdown() -> None:
    """即使收益合格，回撤超限也不能晋级。"""
    good = {
        "annualized_return": 0.12,
        "max_drawdown": -0.25,
        "sharpe": 0.8,
        "calmar": 0.48,
        "excess_return": 0.2,
        "annual_turnover": 4.0,
        "trade_count": 100.0,
        "execution_cost_impact": 0.01,
    }
    metrics = {
        "locked_test": {**good, "max_drawdown": -0.40},
        "full": good,
    }
    annual = {str(year): good for year in range(2015, 2027)}

    gate = study.evaluate_gate(metrics, annual, 0.3)

    assert gate["passed"] is False
    assert gate["checks"]["locked_test_drawdown_within_30pct"] is False


def _factor_row(
    symbol: str,
    forecast_type: str,
    lower: float,
    upper: float,
) -> dict[str, object]:
    """生成单条因子测试数据。"""
    return {
        "symbol": symbol,
        "signal_date": "20200131",
        "publish_date": "20200115",
        "forecast_type": forecast_type,
        "p_change_min": lower,
        "p_change_max": upper,
        "p_change_mid": (lower + upper) / 2,
    }
