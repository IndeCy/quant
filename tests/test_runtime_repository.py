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
