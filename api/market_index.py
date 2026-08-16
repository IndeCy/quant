"""多策略净值对比使用的市场指数 API 助手。"""

from __future__ import annotations

from typing import Any

from data.market_index_comparison import load_market_index_comparison
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


COMPARISON_EXPERIMENT_ID = "nasdaq_gold_60_40_sp500_hurdle_v3"
COMPARISON_SERIES_IDS = (
    COMPARISON_EXPERIMENT_ID,
    "sp500_direct_nasdaq_hurdle_control",
)


def market_index_comparison(paths: RuntimePaths, limit: int = 5000) -> dict[str, Any]:
    """合并市场指数与最新通过门槛的结构化实验净值。"""
    result = load_market_index_comparison(
        paths.benchmark_increment_path,
        limit=limit,
    )
    experiment_series = SystemRepository(
        paths.system_state_path
    ).load_latest_experiment_series(
        COMPARISON_EXPERIMENT_ID,
        series_ids=COMPARISON_SERIES_IDS,
        limit=limit,
    )
    indices = [
        {
            **item,
            "series_id": item["symbol"],
            "series_kind": "market_index",
            "adjust_policy": "index_raw",
        }
        for item in result["indices"]
    ]
    research = [
        {
            **item,
            "symbol": item["series_id"],
            "series_kind": "research",
        }
        for item in experiment_series
    ]
    result["indices"] = [*indices, *research]
    if research:
        result["adjust_policy"] = "mixed"
    as_of_dates = [
        str(item["points"][-1]["trade_date"])
        for item in result["indices"]
        if item["points"]
    ]
    result["as_of"] = min(as_of_dates) if as_of_dates else ""
    if research and result["data_status"] == "MISSING":
        result["data_status"] = "PARTIAL"
    return result
