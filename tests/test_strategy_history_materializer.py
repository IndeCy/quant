"""策略晋级历史资产化测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.strategy_history_materializer import materialize_strategy_backtest_history


def _monitor_frame(strategy_id: str = "candidate_v1") -> pd.DataFrame:
    """构造最小合法监控曲线。"""
    return pd.DataFrame(
        {
            "trade_date": ["20260105", "20260106"],
            "strategy_id": [strategy_id, strategy_id],
            "strategy_name": ["候选策略", "候选策略"],
            "nav": [1.0, 1.01],
            "daily_return": [0.0, 0.01],
            "cumulative_return": [0.0, 0.01],
            "benchmark_id": ["510300", "510300"],
            "benchmark_nav": [1.0, 1.005],
            "benchmark_return": [0.0, 0.005],
            "excess_return": [0.0, 0.005],
            "drawdown": [0.0, 0.0],
            "max_drawdown": [0.0, 0.0],
            "volatility_20": [0.0, 0.0],
            "volatility_60": [0.0, 0.0],
            "sharpe_rolling": [0.0, 0.0],
            "exposure": [1.0, 1.0],
            "turnover_notional": [0.0, 1000.0],
            "total_execution_cost": [0.0, 1.0],
            "failed_order_count": [0, 0],
        }
    )


def test_materialize_strategy_history_writes_only_monitoring_curve(tmp_path) -> None:
    """历史物化只形成看板曲线，不提前创建实盘状态或Paper库。"""
    paths = RuntimePaths(tmp_path)

    result = materialize_strategy_backtest_history(
        paths,
        "candidate_v1",
        _monitor_frame(),
    )

    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("candidate_v1")
    assert result.row_count == 2
    assert result.start_date == "20260105"
    assert result.end_date == "20260106"
    assert history["nav"].tolist() == [1.0, 1.01]
    assert not paths.system_state_path.exists()
    assert not paths.paper_trading_path.exists()


def test_materialize_strategy_history_rejects_mismatched_strategy(tmp_path) -> None:
    """禁止把另一策略的历史误写到当前策略名下。"""
    with pytest.raises(ValueError, match="id mismatch"):
        materialize_strategy_backtest_history(
            RuntimePaths(tmp_path),
            "candidate_v1",
            _monitor_frame("another_strategy"),
        )


def test_materialize_strategy_history_rejects_duplicate_dates(tmp_path) -> None:
    """重复日期说明输入口径不唯一，应在落库前失败。"""
    frame = _monitor_frame()
    frame.loc[1, "trade_date"] = "20260105"

    with pytest.raises(ValueError, match="duplicate trade dates"):
        materialize_strategy_backtest_history(
            RuntimePaths(tmp_path),
            "candidate_v1",
            frame,
        )
