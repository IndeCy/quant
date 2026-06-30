"""本地 API 查询服务测试。"""

from pathlib import Path

import duckdb
import pandas as pd
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from backtest.paper_trading import PaperTradingStore
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


def test_local_api_service_assetizes_mainline_chain_snapshots(tmp_path: Path) -> None:
    """服务启动时应把主线链动模拟盘快照同步为可观测策略指标。"""
    paths = _seed_runtime(tmp_path)
    store = PaperTradingStore(paths.paper_trading_path)
    account_id = store.create_account(
        "主线链动策略",
        "Mainline_Chain_Momentum",
        1_000_000,
        "000001.SH",
        "上证指数",
        "2026-06-05",
    )
    store.record_daily_snapshot(
        account_id,
        "2026-06-05",
        total_value=1_000_000,
        cash=100_000,
        position_value=900_000,
        strategy_return=0.0,
        benchmark_return=0.0,
        excess_return=0.0,
        strongest_chain="通信AI",
        rebalance_signal="NONE",
        target_symbols=["601138.SH"],
    )
    store.record_daily_snapshot(
        account_id,
        "2026-06-06",
        total_value=1_030_000,
        cash=100_000,
        position_value=930_000,
        strategy_return=0.03,
        benchmark_return=0.01,
        excess_return=0.02,
        strongest_chain="半导体",
        rebalance_signal="REBALANCE",
        target_symbols=["600584.SH"],
    )
    store.close()

    service = LocalApiService(paths)

    detail = service.strategy_detail("mainline_chain_b")
    history = service.strategy_series("mainline_chain_b")
    runs = service.runs("mainline_chain_b")

    assert detail is not None
    assert detail["latest_metrics"]["trade_date"] == "20260606"
    assert len(history) == 2
    assert runs[0]["message"] == "最强产业链: 半导体, 信号: REBALANCE"


def test_local_api_service_exposes_factor_detail(tmp_path: Path) -> None:
    """因子详情应包含 as-of 配置和使用该因子的策略关系。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    detail = service.factor_detail("roa")

    assert detail is not None
    assert detail["name"] == "ROA"
    assert detail["config"]["as_of_field"] == "f_ann_date"
    assert detail["strategies"][0]["strategy_id"] == "quality_overlay"
    assert round(detail["strategies"][0]["weight"], 6) == round(1 / 3, 6)


def test_local_api_service_saves_strategy_draft(tmp_path: Path) -> None:
    """本地 API 可保存策略草案，但不触发生产运行。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    saved = service.save_strategy_draft(
        {
            "draft_id": "draft_quality_two_factor",
            "name": "Quality Two Factor Draft",
            "description": "ROA 与 OCF 的研究草案",
            "config": {"top_n": 20, "rebalance": "monthly"},
            "factors": [
                {"factor_id": "roa", "weight": 0.7, "transform": "winsorize_zscore", "enabled": True},
                {"factor_id": "ocf_to_or", "weight": 0.3, "transform": "winsorize_zscore", "enabled": True},
            ],
        }
    )

    assert saved["draft_id"] == "draft_quality_two_factor"
    assert saved["status"] == "draft"
    assert len(service.strategy_drafts()) == 1


def test_local_api_service_exposes_scheduler_status(tmp_path: Path) -> None:
    """设置页需要读取每日自动运行任务状态。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    status = service.scheduler_status()

    assert status["job_store_path"].endswith("state/scheduler.sqlite")
    assert status["start_command"].startswith("/Users/admin/recommend_analysis/.venv/bin/python3")
    assert status["enabled"] is False
    assert status["jobs"] == []


def test_local_api_service_configures_scheduler_job(tmp_path: Path) -> None:
    """设置页登记每日任务后，job store 中应出现 Quality Alpha 任务。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    status = service.configure_scheduler_job({"hour": 17, "minute": 5, "skip_update": True})

    assert status["enabled"] is True
    assert status["schedule"] == "mon-fri 17:05 Asia/Shanghai"
    assert "--skip-update" not in status["start_command"]
    assert [item["job_id"] for item in status["jobs"]] == [
        "daily_data_update_pipeline",
        "quality_overlay_daily_pipeline",
        "mainline_chain_daily_pipeline",
    ]
    assert status["jobs"][1]["schedule"] == "mon-fri 17:15 Asia/Shanghai"
    assert status["jobs"][2]["schedule"] == "mon-fri 17:15 Asia/Shanghai"


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


def test_local_api_service_exposes_research_todos(tmp_path: Path) -> None:
    """研究入口需要读取项目待办资料库。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    todos = service.research_todos()

    assert todos["title"] == "待办资料库"
    assert todos["path"].endswith("docs/todos.md")
    assert "alphaXiv" in todos["content"]


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


def test_local_api_service_reports_data_health(tmp_path: Path) -> None:
    """数据健康接口应汇总行情、基准、监控和系统状态文件。"""
    paths = _seed_runtime(tmp_path)
    with duckdb.connect(str(paths.live_market_increment_path)) as con:
        con.execute("CREATE TABLE daily(ts_code VARCHAR, trade_date VARCHAR)")
        con.execute("CREATE TABLE adj_factor(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("INSERT INTO daily VALUES ('000001.SZ', '20260624')")
        con.execute("INSERT INTO adj_factor VALUES ('000001.SZ', '20260624', 1.0)")
    with duckdb.connect(str(paths.benchmark_increment_path)) as con:
        con.execute("CREATE TABLE fund_daily(ts_code VARCHAR, trade_date VARCHAR)")
        con.execute("CREATE TABLE fund_adj(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE)")
        con.execute("CREATE TABLE index_daily(ts_code VARCHAR, trade_date VARCHAR)")
        con.execute("INSERT INTO fund_daily VALUES ('510300.SH', '20260624')")
        con.execute("INSERT INTO fund_adj VALUES ('510300.SH', '20260624', 1.0)")
        con.execute("INSERT INTO index_daily VALUES ('000001.SH', '20260624')")
    service = LocalApiService(paths)

    health = service.data_health()

    assert health["runtime_root"] == str(paths.root)
    assert health["live_market_increment"]["latest_daily_date"] == "20260624"
    assert health["live_market_increment"]["latest_adj_factor_date"] == "20260624"
    assert health["benchmark_increment"]["latest_fund_date"] == "20260624"
    assert health["benchmark_increment"]["latest_index_date"] == "20260624"
    assert health["monitoring"]["latest_strategy_date"] == "20260624"


def test_local_api_service_returns_run_detail_with_steps(tmp_path: Path) -> None:
    """运行详情应返回运行记录、分步骤状态和当日产物。"""
    paths = _seed_runtime(tmp_path)
    repository = SystemRepository(paths.system_state_path)
    repository.record_run_step("quality_overlay", "20260624", 1, "data_update", "SUCCESS", "增量完成")
    repository.record_run_step("quality_overlay", "20260624", 2, "report_generation", "SUCCESS", "报告完成")
    repository.upsert_report(
        "rebalance_plan",
        "quality_overlay",
        "20260624",
        "调仓建议",
        paths.runs_dir / "20260624" / "rebalance_plan.csv",
        tags=["daily", "execution"],
    )
    service = LocalApiService(paths)

    detail = service.run_detail("quality_overlay", "20260624")

    assert detail is not None
    assert detail["run"]["status"] == "SUCCESS"
    assert [item["step_name"] for item in detail["steps"]] == ["data_update", "report_generation"]
    assert [item["report_type"] for item in detail["artifacts"]] == ["daily_report", "rebalance_plan"]


def test_fastapi_routes_delegate_to_service(tmp_path: Path) -> None:
    """FastAPI 路由层应复用同一套 service 方法。"""
    service = LocalApiService(_seed_runtime(tmp_path))
    client = TestClient(create_app(service))

    assert client.get("/api/health").json()["status"] == "ok"
    scheduler_status = client.get("/api/scheduler/status").json()
    assert scheduler_status["job_id"] == "quality_overlay_daily_pipeline"
    assert scheduler_status["jobs"] == []
    scheduler_response = client.post("/api/scheduler/daily-job", json={"hour": 17, "minute": 5, "skip_update": True})
    assert scheduler_response.status_code == 200
    assert scheduler_response.json()["schedule"] == "mon-fri 17:05 Asia/Shanghai"
    assert len(scheduler_response.json()["jobs"]) == 3
    assert client.get("/api/backup/manifest").json()["items"][0]["name"] == "data"
    assert client.get("/api/services/manifest").json()["services"][0]["name"] == "api"
    assert client.get("/api/services/status").json()["services"][1]["name"] == "frontend"
    assert client.get("/api/logs").status_code == 200
    assert client.get("/api/readiness").json()["checks"][0]["name"] == "tushare_token"
    assert "待办资料库" in client.get("/api/research/todos").json()["content"]
    assert client.get("/api/data/health").json()["runtime_root"].endswith("runtime")
    strategy_ids = [item["strategy_id"] for item in client.get("/api/strategies").json()]
    assert "quality_overlay" in strategy_ids
    assert "mainline_chain_b" in strategy_ids
    assert client.get("/api/factors/roa").json()["strategies"][0]["strategy_id"] == "quality_overlay"
    assert client.get("/api/factors/missing").status_code == 404
    response = client.post(
        "/api/strategy-drafts",
        json={
            "draft_id": "draft_quality_two_factor",
            "name": "Quality Two Factor Draft",
            "description": "ROA 与 OCF 的研究草案",
            "config": {"top_n": 20},
            "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "winsorize_zscore", "enabled": True}],
        },
    )
    assert response.status_code == 200
    assert client.get("/api/strategy-drafts").json()[0]["draft_id"] == "draft_quality_two_factor"
    assert client.get("/api/runs/quality_overlay/20260624").json()["run"]["trade_date"] == "20260624"
    assert client.get("/api/series/strategy/quality_overlay").json()[-1]["trade_date"] == "20260624"
    assert client.get("/api/reports/missing").status_code == 404
    assert client.get("/unknown").status_code == 404
