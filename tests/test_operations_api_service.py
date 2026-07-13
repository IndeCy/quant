"""运行运维 API 服务测试。"""

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from monitoring.metrics import build_market_monitor_frame, build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.portfolio_account import build_account_snapshot
from runtime.repository import SystemRepository
from runtime.strategy_catalog import register_quality_alpha_v1


def _seed_runtime(tmp_path: Path) -> RuntimePaths:
    """构造本地 API 服务所需的最小运行状态。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    system = SystemRepository(paths.system_state_path)
    register_quality_alpha_v1(system)
    system.record_strategy_run("quality_overlay", "20260624", "SUCCESS", paths.runs_dir / "20260624", "完成")
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


def test_local_api_service_generates_and_fills_manual_orders(tmp_path: Path) -> None:
    """本地 API 服务应支持生成、确认和回填人工调仓单。"""
    service = LocalApiService(_seed_runtime(tmp_path))
    snapshot = build_account_snapshot(
        strategy_id="quality_overlay",
        trade_date="20260702",
        total_value=1_000_000.0,
        cash=100_000.0,
        target_weights={"000001.SZ": 0.50},
        actual_positions={"000001.SZ": {"market_value": 400_000.0, "quantity": 10_000, "last_close": 40.0}},
    )
    service.system_repository.upsert_account_snapshot(snapshot)

    batch = service.create_manual_orders_from_account("quality_overlay")
    confirmed = service.confirm_manual_order_batch(batch["batch_id"])
    filled = service.fill_manual_order(batch["orders"][0]["order_id"], {"filled_quantity": 2500, "filled_price": 40.2})

    assert batch["status"] == "DRAFT"
    assert confirmed["status"] == "CONFIRMED"
    assert filled["status"] == "FILLED"


def test_local_api_service_exposes_scheduler_status(tmp_path: Path) -> None:
    """设置页需要读取每日自动运行任务状态。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    status = service.scheduler_status()

    assert status["job_store_path"].endswith("state/scheduler.sqlite")
    assert status["start_command"].startswith("/Users/admin/recommend_analysis/.venv/bin/python3")
    assert status["enabled"] is False
    assert status["jobs"] == []


def test_local_api_service_configures_scheduler_job(tmp_path: Path) -> None:
    """设置页登记每日任务后，job store 中应出现唯一交易流水线任务。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    status = service.configure_scheduler_job({"hour": 17, "minute": 5, "skip_update": True})

    assert status["enabled"] is True
    assert status["schedule"] == "mon-fri 17:05 Asia/Shanghai"
    assert "--skip-update" not in status["start_command"]
    assert [item["job_id"] for item in status["jobs"]] == [
        "pre_market_check_pipeline",
        "market_open_paper_execution_pipeline",
        "daily_trading_pipeline",
        "research_monitor_pipeline",
        "live_risk_guard_pipeline",
        "scheduler_watchdog_pipeline",
    ]
    assert status["jobs"][3]["schedule"] == "mon-fri 17:20 Asia/Shanghai"


def test_local_api_service_exposes_backup_manifest(tmp_path: Path) -> None:
    """设置页需要读取可迁移运行目录清单。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    manifest = service.backup_manifest()

    assert manifest["runtime_root"].endswith("runtime")
    assert [item["name"] for item in manifest["items"]] == ["data", "state", "runs", "reports", "config", "logs"]
    assert "tar -czf" in manifest["backup_command"]


def test_local_api_service_exposes_service_manifest(tmp_path: Path) -> None:
    """设置页需要展示本地服务启动命令和 launchd 模板。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    manifest = service.service_manifest()

    assert manifest["runtime_root"].endswith("runtime")
    assert [item["name"] for item in manifest["services"]] == ["api", "frontend", "scheduler"]
    assert "launchd_plist" in manifest["services"][0]


def test_local_api_service_exposes_service_status(tmp_path: Path) -> None:
    """设置页需要读取本地服务巡检状态。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    status = service.service_status()

    assert [item["name"] for item in status["services"]] == ["api", "frontend", "scheduler"]
    assert status["services"][0]["check"] == "tcp:127.0.0.1:8765"


def test_local_api_service_exposes_runtime_logs(tmp_path: Path) -> None:
    """运行日志应通过 API 统一索引和读取。"""
    paths = _seed_runtime(tmp_path)
    (paths.logs_dir / "api.log").write_text("api ok\n", encoding="utf-8")
    service = LocalApiService(paths)

    logs = service.logs()
    content = service.log_content(logs[0]["log_id"])

    assert logs[0]["name"] == "api.log"
    assert content is not None
    assert content["content"] == "api ok\n"


def test_local_api_service_exposes_readiness_report(tmp_path: Path, monkeypatch) -> None:
    """总览页需要读取生产候选运行就绪度。"""
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    service = LocalApiService(_seed_runtime(tmp_path))

    report = service.readiness()

    assert report["status"] in {"READY", "NOT_READY"}
    assert [item["name"] for item in report["checks"]][:3] == ["tushare_token", "live_market_data", "benchmark_data"]


def test_local_api_service_readiness_includes_live_preflight_items(tmp_path: Path, monkeypatch) -> None:
    """实盘前就绪度应包含备份、通知、调仓和券商权限边界。"""
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setenv("BARK_PUSH_URL", "https://api.day.app/key")
    monkeypatch.delenv("QUANT_ENABLE_BROKER_TRADING", raising=False)
    service = LocalApiService(_seed_runtime(tmp_path))

    report = service.readiness()

    names = [item["name"] for item in report["checks"]]
    assert "backup_manifest" in names
    assert "notification_channel" in names
    assert "manual_order_workflow" in names
    assert "broker_permission_boundary" in names


def test_fastapi_manual_order_routes(tmp_path: Path) -> None:
    """FastAPI 应暴露手工调仓单生成、确认和成交回填入口。"""
    service = LocalApiService(_seed_runtime(tmp_path))
    snapshot = build_account_snapshot(
        strategy_id="quality_overlay",
        trade_date="20260702",
        total_value=1_000_000.0,
        cash=100_000.0,
        target_weights={"000001.SZ": 0.50},
        actual_positions={"000001.SZ": {"market_value": 400_000.0, "quantity": 10_000, "last_close": 40.0}},
    )
    service.system_repository.upsert_account_snapshot(snapshot)
    client = TestClient(create_app(service))

    created = client.post("/api/manual-orders/from-account/quality_overlay")
    loaded = client.get("/api/manual-orders/quality_overlay")
    confirmed = client.post(f"/api/manual-orders/batches/{created.json()['batch_id']}/confirm")
    order_id = confirmed.json()["orders"][0]["order_id"]
    filled = client.post(f"/api/manual-orders/orders/{order_id}/fill", json={"filled_quantity": 2500, "filled_price": 40.2})

    assert created.status_code == 200
    assert loaded.json()["status"] == "DRAFT"
    assert confirmed.json()["status"] == "CONFIRMED"
    assert filled.json()["status"] == "FILLED"
