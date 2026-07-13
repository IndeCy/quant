"""系统状态库测试。"""

from pathlib import Path

from runtime.repository import SystemRepository


def test_system_repository_records_latest_run(tmp_path: Path) -> None:
    """同一策略同一日期重复运行时，只保留最新状态。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    repository.record_strategy_run("quality_overlay", "20260624", "FAILED", tmp_path / "runs" / "20260624", "数据失败")
    repository.record_strategy_run("quality_overlay", "20260624", "SUCCESS", tmp_path / "runs" / "20260624", "完成")

    latest = repository.latest_run("quality_overlay")
    assert latest is not None
    assert latest["trade_date"] == "20260624"
    assert latest["status"] == "SUCCESS"
    assert latest["message"] == "完成"


def test_system_repository_indexes_reports_idempotently(tmp_path: Path) -> None:
    """报告索引按 report_id 幂等更新，前端无需扫描目录。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    report_path = tmp_path / "runs" / "20260624" / "daily_report.md"

    repository.upsert_report(
        report_type="daily_report",
        strategy_id="quality_overlay",
        trade_date="20260624",
        title="日报",
        file_path=report_path,
        tags=["daily", "quality"],
    )
    repository.upsert_report(
        report_type="daily_report",
        strategy_id="quality_overlay",
        trade_date="20260624",
        title="日报修订",
        file_path=report_path,
        tags=["daily"],
    )

    reports = repository.list_reports("quality_overlay")
    assert len(reports) == 1
    assert reports[0]["title"] == "日报修订"
    assert reports[0]["file_path"] == str(report_path)
    assert reports[0]["tags"] == ["daily"]


def test_system_repository_loads_strategy_factor_definition(tmp_path: Path) -> None:
    """策略定义要能表达因子自由组合和权重。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    repository.upsert_factor("roe", "ROE", "quality", "higher_is_better", "fina_indicator")
    repository.upsert_factor("roa", "ROA", "quality", "higher_is_better", "fina_indicator")
    repository.upsert_strategy("quality_overlay", "Quality Alpha V1", "active", "factor_topn_monthly")
    repository.replace_strategy_factors(
        "quality_overlay",
        [
            {"factor_id": "roe", "weight": 0.4, "transform": "winsorize_zscore"},
            {"factor_id": "roa", "weight": 0.6, "transform": "winsorize_zscore"},
        ],
    )

    definition = repository.load_strategy_definition("quality_overlay")

    assert definition is not None
    assert definition["strategy_id"] == "quality_overlay"
    assert definition["status"] == "active"
    assert [item["factor_id"] for item in definition["factors"]] == ["roa", "roe"]
    assert sum(item["weight"] for item in definition["factors"]) == 1.0


def test_system_repository_records_run_steps(tmp_path: Path) -> None:
    """运行中心需要能回看每日 pipeline 分步骤状态。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    repository.record_run_step("quality_overlay", "20260624", 1, "data_update", "SUCCESS", "增量完成")
    repository.record_run_step("quality_overlay", "20260624", 2, "strategy_run", "SUCCESS", "策略完成")
    repository.record_run_step("quality_overlay", "20260624", 2, "strategy_run", "FAILED", "重跑失败")

    steps = repository.list_run_steps("quality_overlay", "20260624")
    assert [item["step_name"] for item in steps] == ["data_update", "strategy_run"]
    assert steps[1]["status"] == "FAILED"
    assert steps[1]["message"] == "重跑失败"


def test_system_repository_loads_factor_definition_with_strategy_usage(tmp_path: Path) -> None:
    """因子详情需要展示被哪些策略使用，支撑后续因子组合维护。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    repository.upsert_factor(
        "roa",
        "ROA",
        "quality",
        "higher_is_better",
        "fina_indicator",
        config={"as_of_field": "f_ann_date"},
    )
    repository.upsert_strategy("quality_overlay", "Quality Alpha V1", "active", "factor_topn_monthly")
    repository.replace_strategy_factors(
        "quality_overlay",
        [{"factor_id": "roa", "weight": 0.6, "transform": "winsorize_zscore"}],
    )

    definition = repository.load_factor_definition("roa")

    assert definition is not None
    assert definition["factor_id"] == "roa"
    assert definition["config"]["as_of_field"] == "f_ann_date"
    assert definition["strategies"] == [
        {
            "strategy_id": "quality_overlay",
            "name": "Quality Alpha V1",
            "status": "active",
            "weight": 0.6,
            "transform": "winsorize_zscore",
            "enabled": True,
        }
    ]


def test_system_repository_saves_strategy_draft_with_factor_weights(tmp_path: Path) -> None:
    """策略草案只保存组合定义，不影响生产策略注册表。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    repository.upsert_strategy_draft(
        draft_id="draft_quality_two_factor",
        name="Quality Two Factor Draft",
        description="ROA 与 OCF 的研究草案",
        config={"top_n": 20, "rebalance": "monthly"},
        factors=[
            {"factor_id": "roa", "weight": 0.7, "transform": "winsorize_zscore", "enabled": True},
            {"factor_id": "ocf_to_or", "weight": 0.3, "transform": "winsorize_zscore", "enabled": True},
        ],
    )

    draft = repository.load_strategy_draft("draft_quality_two_factor")

    assert draft is not None
    assert draft["draft_id"] == "draft_quality_two_factor"
    assert draft["status"] == "draft"
    assert draft["config"]["top_n"] == 20
    assert [item["factor_id"] for item in draft["factors"]] == ["ocf_to_or", "roa"]
    assert sum(item["weight"] for item in draft["factors"]) == 1.0
    assert repository.list_strategy_drafts()[0]["name"] == "Quality Two Factor Draft"


def test_system_repository_saves_research_notes(tmp_path: Path) -> None:
    """通用投研记录应能保存最终报告正文和标签。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    note = repository.upsert_research_note(
        {
            "note_id": "stock_300308_20260701",
            "title": "中际旭创个股投研",
            "note_type": "stock",
            "linked_type": "stock",
            "linked_id": "300308.SZ",
            "summary": "AI光模块高景气高波动样本",
            "content": "# 中际旭创\n高端光模块龙头。",
            "tags": ["AI算力", "光模块"],
            "source": "agent_report",
            "status": "active",
        }
    )

    notes = repository.list_research_notes()
    stock_notes = repository.list_research_notes(note_type="stock")

    assert note["linked_id"] == "300308.SZ"
    assert note["tags"] == ["AI算力", "光模块"]
    assert notes[0]["note_id"] == "stock_300308_20260701"
    assert stock_notes[0]["content"].startswith("# 中际旭创")


def test_system_repository_saves_opportunity_theme_and_monitor_run(tmp_path: Path) -> None:
    """机会观察池应保存主题、候选股和每日研究监控结果。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    repository.upsert_opportunity_theme(
        {
            "theme_id": "ai_optical_module_powerlaw",
            "name": "AI光模块高赔率机会",
            "status": "observation",
            "stage": "Observation",
            "horizon_years": 10,
            "thesis_type": "power_law_industry",
            "thesis": "产业右偏机会观察，不进入交易策略。",
            "upgrade_rule": "至少3只样本达到S/A。",
            "disconfirm_rule": "核心财务或技术路线被证伪。",
            "linked_note_id": "strategy_powerlaw_industry_20260701",
            "tags": ["AI算力", "光模块"],
        }
    )
    repository.upsert_opportunity_stock(
        {
            "theme_id": "ai_optical_module_powerlaw",
            "symbol": "300308.SZ",
            "name": "中际旭创",
            "status": "active",
            "watch_level": "B",
            "chain_role": "核心龙头",
            "conviction": "高",
            "first_observed_date": "20260701",
            "thesis": "光模块龙头观察样本。",
            "disconfirm_condition": "财务增长失速。",
            "evidence": {"upgrade_path": "Observation"},
        }
    )
    repository.update_opportunity_stock_monitor(
        "ai_optical_module_powerlaw",
        "300308.SZ",
        "A",
        {"ret_120d": 0.35, "netprofit_yoy": 42.0},
        "20260701",
        {"upgrade_path": "Confirming", "powerlaw_score": 60.0},
    )
    repository.record_research_monitor_run(
        "ai_optical_module_powerlaw",
        "20260701",
        "SUCCESS",
        "1 个A级，继续观察",
        {"a_count": 1, "upgrade_candidate": False},
    )
    repository.upsert_opportunity_stock(
        {
            "theme_id": "ai_optical_module_powerlaw",
            "symbol": "300308.SZ",
            "name": "中际旭创",
            "status": "active",
            "watch_level": "B",
            "chain_role": "核心龙头",
            "conviction": "高",
            "first_observed_date": "20260701",
            "thesis": "服务重启时重新登记元数据。",
            "disconfirm_condition": "财务增长失速。",
        }
    )

    theme = repository.load_opportunity_theme("ai_optical_module_powerlaw")

    assert theme["tags"] == ["AI算力", "光模块"]
    assert theme["horizon_years"] == 10
    assert theme["thesis_type"] == "power_law_industry"
    assert theme["upgrade_rule"] == "至少3只样本达到S/A。"
    assert theme["stocks"][0]["chain_role"] == "核心龙头"
    assert theme["stocks"][0]["evidence"]["upgrade_path"] == "Confirming"
    assert theme["stocks"][0]["watch_level"] == "A"
    assert theme["stocks"][0]["metrics"]["ret_120d"] == 0.35
    assert theme["monitor_runs"][0]["summary"] == "1 个A级，继续观察"
    assert theme["monitor_runs"][0]["metrics"]["upgrade_candidate"] is False


def test_system_repository_records_opportunity_direction_rankings(tmp_path: Path) -> None:
    """每日方向排行应按强势分倒序读取，支撑研究页前排展示。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    theme = {
        "theme_id": "robotics_emerging",
        "name": "人形机器人早期机会",
        "status": "observation",
        "stage": "Observation",
    }

    repository.record_opportunity_direction_ranking(
        "20260701",
        theme,
        {
            "strength_score": 72.0,
            "theme_early_signal_score": 80.0,
            "theme_maturity_score": 20.0,
            "theme_crowding_score": 15.0,
            "upgrade_candidate": True,
        },
        "早期信号增强",
    )
    repository.record_opportunity_direction_ranking(
        "20260701",
        {**theme, "theme_id": "case_study", "name": "历史案例"},
        {
            "strength_score": 12.0,
            "theme_early_signal_score": 45.0,
            "theme_maturity_score": 80.0,
            "theme_crowding_score": 85.0,
            "upgrade_candidate": False,
        },
        "案例校准",
    )

    rankings = repository.list_opportunity_direction_rankings()

    assert [item["theme_id"] for item in rankings] == ["robotics_emerging", "case_study"]
    assert rankings[0]["strength_score"] == 72.0
    assert rankings[0]["upgrade_candidate"] is True
    assert rankings[0]["metrics"]["theme_early_signal_score"] == 80.0
