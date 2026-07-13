"""本地 API 查询服务测试。"""

from pathlib import Path

import duckdb
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


def test_local_api_service_exposes_innovative_drug_observer(tmp_path: Path) -> None:
    """本地 API 应暴露创新药观察策略定义和实例。"""
    service = LocalApiService(RuntimePaths(tmp_path / "runtime"))

    strategies = service.strategies()
    instances = service.strategy_instances()

    assert any(item["strategy_id"] == "innovative_drug_globalization_observer_v0" for item in strategies)
    observer = next(item for item in instances if item["strategy_id"] == "innovative_drug_globalization_observer_v0")
    assert observer["status"] == "research_observation"
    assert observer["template_id"] == "opportunity_observer"


def test_local_api_service_exposes_factor_detail(tmp_path: Path) -> None:
    """因子详情应包含 as-of 配置和使用该因子的策略关系。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    detail = service.factor_detail("roa")
    contract = service.factor_contract_detail("roa")

    assert detail is not None
    assert detail["name"] == "ROA"
    assert detail["config"]["as_of_field"] == "f_ann_date"
    assert detail["strategies"][0]["strategy_id"] == "quality_overlay"
    assert round(detail["strategies"][0]["weight"], 6) == round(1 / 3, 6)
    assert contract is not None
    assert contract["as_of_field"] == "f_ann_date"
    assert contract["input_datasets"] == ["fina_indicator_duckdb"]


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


def test_local_api_service_saves_research_ideas(tmp_path: Path) -> None:
    """本地 API 应支持沉淀外部因子和策略想法。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    factor = service.save_factor_idea(
        {
            "idea_id": "profit_stability",
            "title": "盈利稳定性",
            "raw_description": "过去三年ROE波动率越低越好",
            "source": "external_note",
            "hypothesis": "盈利稳定公司更可能获得稳定估值溢价",
            "required_data": ["roe", "f_ann_date"],
            "as_of_requirement": "必须使用财报披露日",
            "direction": "lower_is_better",
            "status": "draft",
        }
    )
    strategy = service.save_strategy_idea(
        {
            "idea_id": "quality_low_vol_top30",
            "title": "高质量低波Top30",
            "raw_description": "高ROA、高经营现金流、低波动，月频调仓，Top30",
            "source": "external_strategy",
            "hypothesis": "质量和低波风险溢价共同发挥作用",
            "candidate_template": "factor_topn_monthly",
            "required_factors": ["roa", "ocf_to_or", "low_volatility"],
            "status": "structured",
        }
    )

    assert factor["required_data"] == ["roe", "f_ann_date"]
    assert service.factor_ideas()[0]["idea_id"] == "profit_stability"
    assert strategy["required_factors"] == ["roa", "ocf_to_or", "low_volatility"]
    assert service.strategy_ideas()[0]["idea_id"] == "quality_low_vol_top30"


def test_local_api_service_saves_research_notes(tmp_path: Path) -> None:
    """投研模块应支持保存个股、策略等通用研究报告。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    saved = service.save_research_note(
        {
            "note_id": "stock_300308_20260701",
            "title": "中际旭创个股投研",
            "note_type": "stock",
            "linked_type": "stock",
            "linked_id": "300308.SZ",
            "summary": "AI光模块高景气高波动样本",
            "content": "# 中际旭创\n适合作为趋势增强观察对象。",
            "tags": ["AI算力", "光模块"],
            "source": "agent_report",
            "status": "active",
        }
    )

    notes = service.research_notes()
    detail = service.research_note_detail("stock_300308_20260701")

    assert saved["note_type"] == "stock"
    assert notes[0]["title"] == "中际旭创个股投研"
    assert detail is not None
    assert detail["content"].startswith("# 中际旭创")


def test_local_api_service_exposes_strategy_templates_and_instances(tmp_path: Path) -> None:
    """本地 API 应支持策略模板和可运行策略实例。"""
    service = LocalApiService(_seed_runtime(tmp_path))

    templates = service.strategy_templates()
    saved = service.save_strategy_instance(
        {
            "strategy_id": "quality_roa_ocf_v2",
            "name": "Quality ROA OCF V2",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": ["listed_3y"],
            "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "winsorize_zscore"}],
            "construction": {"top_n": 20, "weighting": "equal_weight"},
            "risk_overlay": "",
            "benchmark": "510300",
        }
    )

    assert templates[0]["template_id"] == "factor_topn_monthly"
    assert saved["strategy_id"] == "quality_roa_ocf_v2"
    assert saved["enabled"] is True
    instance_ids = [item["strategy_id"] for item in service.strategy_instances()]
    assert "quality_roa_ocf_v2" in instance_ids
    assert "quality_overlay" in instance_ids
    assert "mainline_chain_factor_v1" in instance_ids


def test_local_api_service_transitions_strategy_lifecycle(tmp_path: Path) -> None:
    """本地 API 应通过生命周期状态机更新策略状态。"""
    service = LocalApiService(_seed_runtime(tmp_path))
    service.save_strategy_instance(
        {
            "strategy_id": "quality_lifecycle_test",
            "name": "Quality Lifecycle Test",
            "template_id": "factor_topn_monthly",
            "status": "draft",
            "enabled": False,
            "universe": "all_a",
            "filters": [],
            "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "winsorize_zscore"}],
            "construction": {"top_n": 20, "weighting": "equal_weight"},
            "risk_overlay": "",
            "benchmark": "510300",
        }
    )

    research = service.transition_strategy_instance(
        "quality_lifecycle_test",
        {"target_status": "research"},
    )

    assert research["status"] == "research"
    assert research["enabled"] is False


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


def test_local_api_service_refreshes_data_catalog(tmp_path: Path) -> None:
    """本地 API 应能刷新并读取 Data Catalog。"""
    paths = _seed_runtime(tmp_path)
    with duckdb.connect(str(paths.data_dir / "daily.duckdb")) as con:
        con.execute("CREATE TABLE daily(trade_date VARCHAR, close DOUBLE)")
        con.execute("INSERT INTO daily VALUES ('20260702', 10.2)")
    service = LocalApiService(paths)

    refresh = service.refresh_data_catalog({"roots": [str(paths.data_dir)]})
    sources = service.data_sources()
    detail = service.data_source_detail("daily_duckdb")

    assert refresh["status"] == "SUCCESS"
    assert sources[0]["dataset_id"] == "daily_duckdb"
    assert detail is not None
    assert detail["tables"][0]["latest_date"] == "20260702"


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
    assert scheduler_status["job_id"] == "daily_trading_pipeline"
    assert scheduler_status["jobs"] == []
    scheduler_response = client.post("/api/scheduler/daily-job", json={"hour": 17, "minute": 5, "skip_update": True})
    assert scheduler_response.status_code == 200
    assert scheduler_response.json()["schedule"] == "mon-fri 17:05 Asia/Shanghai"
    assert len(scheduler_response.json()["jobs"]) == 6
    assert client.get("/api/backup/manifest").json()["items"][0]["name"] == "data"
    assert client.get("/api/services/manifest").json()["services"][0]["name"] == "api"
    assert client.get("/api/services/status").json()["services"][1]["name"] == "frontend"
    assert client.get("/api/logs").status_code == 200
    assert client.get("/api/readiness").json()["checks"][0]["name"] == "tushare_token"

def test_fastapi_manual_daily_run_uses_unified_pipeline(monkeypatch, tmp_path: Path) -> None:
    """API 手动补跑也必须调用统一交易流水线。"""
    service = LocalApiService(_seed_runtime(tmp_path))
    client = TestClient(create_app(service))
    calls = []
    def fake_pipeline(paths, push: bool, source: str, trade_date: str | None = None):
        calls.append({"paths": paths, "push": push, "source": source, "trade_date": trade_date})
        return {"trade_date": trade_date or "20260702", "status": "SUCCESS", "source": source}

    monkeypatch.setattr("api.service.run_production_daily_pipeline", fake_pipeline)

    response = client.post("/api/pipeline/daily-run", json={"push": True, "trade_date": "20260707"})

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert calls == [{"paths": service.paths, "push": True, "source": "api", "trade_date": "20260707"}]
    assert "待办资料库" in client.get("/api/research/todos").json()["content"]
    factor_response = client.post(
        "/api/research/factor-ideas",
        json={
            "idea_id": "profit_stability",
            "title": "盈利稳定性",
            "raw_description": "过去三年ROE波动率越低越好",
            "source": "external_note",
            "hypothesis": "盈利稳定公司更可能获得稳定估值溢价",
            "required_data": ["roe"],
            "as_of_requirement": "必须使用财报披露日",
            "direction": "lower_is_better",
            "status": "draft",
        },
    )
    assert factor_response.status_code == 200
    assert client.get("/api/research/factor-ideas").json()[0]["idea_id"] == "profit_stability"
    strategy_response = client.post(
        "/api/research/strategy-ideas",
        json={
            "idea_id": "quality_low_vol_top30",
            "title": "高质量低波Top30",
            "raw_description": "高ROA、高经营现金流、低波动，月频调仓，Top30",
            "source": "external_strategy",
            "hypothesis": "质量和低波风险溢价共同发挥作用",
            "candidate_template": "factor_topn_monthly",
            "required_factors": ["roa"],
            "status": "structured",
        },
    )
    assert strategy_response.status_code == 200
    assert client.get("/api/research/strategy-ideas").json()[0]["idea_id"] == "quality_low_vol_top30"
    assert client.get("/api/strategy-templates").json()[0]["template_id"] == "factor_topn_monthly"
    instance_response = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "quality_roa_ocf_v2",
            "name": "Quality ROA OCF V2",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": ["listed_3y"],
            "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "winsorize_zscore"}],
            "construction": {"top_n": 20, "weighting": "equal_weight"},
            "risk_overlay": "",
            "benchmark": "510300",
        },
    )
    assert instance_response.status_code == 200
    strategy_instances = client.get("/api/strategy-instances").json()
    assert "quality_roa_ocf_v2" in [item["strategy_id"] for item in strategy_instances]
    assert client.get("/api/strategy-instances/quality_roa_ocf_v2/state").json()["holdings"] == []
    assert client.get("/api/accounts/quality_roa_ocf_v2").status_code == 404
    transition_response = client.post(
        "/api/strategy-instances/quality_roa_ocf_v2/transition",
        json={"target_status": "paused", "enable": False},
    )
    assert transition_response.status_code == 200
    assert transition_response.json()["status"] == "paused"
    assert client.get("/api/data/health").json()["runtime_root"].endswith("runtime")
    assert client.post("/api/data/catalog/refresh", json={"roots": [str(service.paths.data_dir)]}).status_code == 200
    assert client.get("/api/data/sources").status_code == 200
    assert client.get("/api/data/sources/missing").status_code == 404
    quality_response = client.post("/api/data/quality-gate", json={"min_trade_date": "20260702"})
    assert quality_response.status_code == 200
    assert quality_response.json()["status"] in {"PASS", "FAIL"}
    strategy_ids = [item["strategy_id"] for item in client.get("/api/strategies").json()]
    assert "quality_overlay" in strategy_ids
    assert "mainline_chain_factor_v1" in strategy_ids
    assert "mainline_chain_b" not in strategy_ids
    assert client.get("/api/factors/roa").json()["strategies"][0]["strategy_id"] == "quality_overlay"
    assert client.get("/api/factor-contracts").json()[0]["factor_id"]
    assert client.get("/api/factor-contracts/roa").json()["as_of_field"] == "f_ann_date"
    assert client.get("/api/factor-contracts/missing").status_code == 404
    assert client.get("/api/factors/missing").status_code == 404
    note_response = client.post(
        "/api/research/notes",
        json={
            "note_id": "stock_300308_20260701",
            "title": "中际旭创个股投研",
            "note_type": "stock",
            "linked_type": "stock",
            "linked_id": "300308.SZ",
            "summary": "AI光模块高景气高波动样本",
            "content": "# 中际旭创\n适合作为趋势增强观察对象。",
            "tags": ["AI算力", "光模块"],
            "source": "agent_report",
            "status": "active",
        },
    )
    assert note_response.status_code == 200
    assert client.get("/api/research/notes").json()[0]["linked_id"] == "300308.SZ"
    assert client.get("/api/research/notes/stock_300308_20260701").json()["note_type"] == "stock"
    opportunities = client.get("/api/research/opportunities").json()
    optical = next(item for item in opportunities if item["theme_id"] == "ai_optical_module_powerlaw")
    assert optical["stocks"][0]["symbol"] in {"000063.SZ", "300308.SZ", "300394.SZ", "300502.SZ", "601138.SH"}
    assert client.get("/api/research/opportunity-rankings").status_code == 200
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
