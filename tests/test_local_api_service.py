"""本地 API 查询服务测试。"""

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from monitoring.metrics import build_market_monitor_frame, build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_catalog import register_quality_alpha_v1


def _seed_runtime(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    system = SystemRepository(paths.system_state_path)
    register_quality_alpha_v1(system)
    system.record_strategy_run("quality_overlay", "20260624", "SUCCESS", paths.runs_dir / "20260624", "完成")
    system.upsert_report(
        "daily_report",
        "quality_overlay",
        "20260624",
        "每日策略报告",
        paths.runs_dir / "20260624" / "daily_report.md",
        tags=["daily"],
    )

    dates = pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24"])
    values = pd.Series([100.0, 101.0, 103.0], index=dates)
    benchmark = pd.Series([1.0, 1.01, 1.02], index=dates)
    monitoring = MonitoringRepository(paths.monitoring_path)
    monitoring.upsert_strategy_daily(
        build_strategy_monitor_frame(
            strategy_id="quality_overlay",
            strategy_name="Quality Alpha V1",
            daily_values=values,
            benchmark_values=benchmark,
            exposure=pd.Series([1.0, 1.0, 0.3], index=dates),
            total_cost=12.0,
            failed_order_count=0,
            turnover_notional=1000.0,
        )
    )
    monitoring.upsert_market_daily(build_market_monitor_frame("510300", benchmark))
    return paths


def test_local_api_service_exposes_strategy_detail(tmp_path: Path) -> None:
    """策略详情应聚合定义、运行状态和最新指标。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    detail = service.strategy_detail("quality_overlay")

    assert detail is not None
    assert detail["name"] == "Quality Alpha V1"
    assert detail["latest_run"]["status"] == "SUCCESS"
    assert detail["latest_metrics"]["trade_date"] == "20260624"
    assert len(detail["factors"]) == 3


def test_local_api_service_lists_reports_and_series(tmp_path: Path) -> None:
    """报告索引和曲线数据应可直接供前端消费。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    reports = service.reports("quality_overlay")
    strategy_series = service.strategy_series("quality_overlay")
    market_series = service.market_series("510300")

    assert reports[0]["report_type"] == "daily_report"
    assert strategy_series[-1]["trade_date"] == "20260624"
    assert market_series[-1]["benchmark_id"] == "510300"


def test_local_api_service_reads_registered_report_content(tmp_path: Path) -> None:
    """报告详情接口只能读取已登记报告的文件内容。"""
    paths = _seed_runtime(tmp_path)
    report_path = paths.runs_dir / "20260624" / "daily_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# 日报\n\n- 状态：正常\n", encoding="utf-8")
    service = LocalApiService(paths)
    report_id = service.reports("quality_overlay")[0]["report_id"]

    content = service.report_content(report_id)

    assert content is not None
    assert content["report_id"] == report_id
    assert content["title"] == "每日策略报告"
    assert content["content"] == "# 日报\n\n- 状态：正常\n"


def test_fastapi_routes_delegate_to_service(tmp_path: Path) -> None:
    """FastAPI 路由层应复用同一套 service 方法。"""
    service = LocalApiService(_seed_runtime(tmp_path))
    client = TestClient(create_app(service))

    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/strategies").json()[0]["strategy_id"] == "quality_overlay"
    assert client.get("/api/series/strategy/quality_overlay").json()[-1]["trade_date"] == "20260624"
    assert client.get("/api/reports/missing").status_code == 404
    assert client.get("/unknown").status_code == 404
