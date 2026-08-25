"""总览首屏聚合 API。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, Response

from api.market_beta import latest_market_beta
from api.market_index import market_index_comparison
from api.service import LocalApiService

DASHBOARD_SERIES_FIELDS = (
    "trade_date",
    "strategy_id",
    "nav",
    "paper_nav",
    "risk_adjusted_nav",
    "benchmark_nav",
    "drawdown",
    "cumulative_return",
)


def register_dashboard_routes(app: FastAPI, service: LocalApiService, *, warm: bool = False) -> None:
    """注册不触发外部更新的总览首屏聚合接口。"""
    cache_lock = Lock()
    cached_signature: tuple[tuple[str, int, int], ...] = ()
    cached_content = ""
    if warm:
        payload = _build_dashboard_payload(service)
        cached_content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        cached_signature = _dashboard_source_signature(service)

    @app.get("/api/dashboard/bootstrap")
    def dashboard_bootstrap() -> Response:
        nonlocal cached_content, cached_signature
        signature = _dashboard_source_signature(service)
        cache_status = "HIT"
        with cache_lock:
            if not cached_content or signature != cached_signature:
                payload = _build_dashboard_payload(service)
                cached_content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                cached_signature = _dashboard_source_signature(service)
                cache_status = "MISS"
        return Response(
            content=cached_content,
            media_type="application/json",
            headers={"X-Dashboard-Cache": cache_status},
        )


def _build_dashboard_payload(service: LocalApiService) -> dict[str, Any]:
    """顺序聚合首屏数据，避免大量并发查询和重复 JSON 编码。"""
    strategies = service.strategies()
    details = {
        strategy["strategy_id"]: service.strategy_detail(strategy["strategy_id"])
        for strategy in strategies
    }
    series_map = {
        strategy["strategy_id"]: _compact_strategy_series(service.strategy_series(strategy["strategy_id"]))
        for strategy in strategies
    }
    instance_states = {
        instance["strategy_id"]: service.strategy_instance_state(instance["strategy_id"])
        for instance in service.strategy_instances()
    }
    return {
        "strategies": strategies,
        "strategy_details": details,
        "strategy_series_map": series_map,
        "strategy_instance_states": instance_states,
        "market_index_comparison": market_index_comparison(service.paths),
        "market_series": service.market_series("510300")[-240:],
        "market_beta": latest_market_beta(service.paths),
        "readiness": service.readiness(),
        "runs": service.runs(limit=30),
        "reports": service.reports(),
    }


def _compact_strategy_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅保留总览首屏绘图字段，单策略详情按需读取完整序列。"""
    return [{field: row.get(field) for field in DASHBOARD_SERIES_FIELDS} for row in rows]


def _dashboard_source_signature(service: LocalApiService) -> tuple[tuple[str, int, int], ...]:
    """用本地状态文件版本自动失效首屏缓存。"""
    paths = service.paths
    sources = [
        paths.monitoring_path,
        paths.system_state_path,
        paths.paper_trading_path,
        paths.benchmark_increment_path,
        paths.beta_increment_path,
        paths.limit_list_increment_path,
        paths.runs_dir,
        paths.reports_dir,
    ]
    return tuple(_path_stamp(path) for path in sources)


def _path_stamp(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (str(path), 0, 0)
    return (str(path), stat.st_mtime_ns, stat.st_size)
