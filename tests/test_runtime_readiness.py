"""运行就绪度测试。"""

from runtime.readiness import build_readiness_report


def test_build_readiness_report_marks_ready_when_core_checks_pass() -> None:
    """核心检查均通过时，系统应显示可运行。"""
    report = build_readiness_report(
        token_present=True,
        data_health={
            "live_market_increment": {"exists": True, "latest_daily_date": "20260626", "latest_adj_factor_date": "20260626"},
            "benchmark_increment": {"exists": True, "latest_fund_date": "20260626", "latest_fund_adj_date": "20260626"},
            "monitoring": {"exists": True, "latest_strategy_date": "20260626"},
            "system_state": {"exists": True, "latest_run_date": "20260626"},
        },
        scheduler_status={"enabled": True},
        service_status={
            "services": [
                {"name": "api", "running": True},
                {"name": "frontend", "running": True},
                {"name": "scheduler", "running": True},
            ]
        },
    )

    assert report["status"] == "READY"
    assert all(item["status"] == "PASS" for item in report["checks"])


def test_build_readiness_report_marks_not_ready_for_missing_token_and_data() -> None:
    """缺少 token 或关键数据时，系统不应被认为已准备好。"""
    report = build_readiness_report(
        token_present=False,
        data_health={
            "live_market_increment": {"exists": False, "latest_daily_date": None, "latest_adj_factor_date": None},
            "benchmark_increment": {"exists": True, "latest_fund_date": "20260626", "latest_fund_adj_date": "20260625"},
            "monitoring": {"exists": True, "latest_strategy_date": "20260626"},
            "system_state": {"exists": True, "latest_run_date": "20260626"},
        },
        scheduler_status={"enabled": False},
        service_status={"services": [{"name": "api", "running": True}, {"name": "frontend", "running": False}]},
    )

    assert report["status"] == "NOT_READY"
    failed = [item["name"] for item in report["checks"] if item["status"] == "FAIL"]
    assert failed == [
        "tushare_token",
        "live_market_data",
        "benchmark_data",
        "scheduler_job",
        "frontend_service",
        "scheduler_service",
    ]


def test_build_readiness_report_includes_live_trading_preflight_checks() -> None:
    """实盘前审计应覆盖备份、通知、手工调仓和券商权限边界。"""
    report = build_readiness_report(
        token_present=True,
        data_health={
            "live_market_increment": {"exists": True, "latest_daily_date": "20260626", "latest_adj_factor_date": "20260626"},
            "benchmark_increment": {"exists": True, "latest_fund_date": "20260626", "latest_fund_adj_date": "20260626"},
            "monitoring": {"exists": True},
            "system_state": {"exists": True},
        },
        scheduler_status={"enabled": True},
        service_status={
            "services": [
                {"name": "api", "running": True},
                {"name": "frontend", "running": True},
                {"name": "scheduler", "running": True},
            ]
        },
        backup_manifest={"items": [{"name": name, "exists": True} for name in ["data", "state", "runs", "reports", "config", "logs"]]},
        notification_configured=True,
        manual_order_ready=True,
        broker_auto_trading_enabled=False,
    )

    names = [item["name"] for item in report["checks"]]
    assert report["status"] == "READY"
    assert names[-4:] == ["backup_manifest", "notification_channel", "manual_order_workflow", "broker_permission_boundary"]


def test_build_readiness_report_fails_when_broker_auto_trading_is_enabled() -> None:
    """第一阶段禁止自动下单，开启券商自动交易时必须阻断。"""
    report = build_readiness_report(
        token_present=True,
        data_health={
            "live_market_increment": {"exists": True, "latest_daily_date": "20260626", "latest_adj_factor_date": "20260626"},
            "benchmark_increment": {"exists": True, "latest_fund_date": "20260626", "latest_fund_adj_date": "20260626"},
            "monitoring": {"exists": True},
            "system_state": {"exists": True},
        },
        scheduler_status={"enabled": True},
        service_status={"services": [{"name": "api", "running": True}, {"name": "frontend", "running": True}, {"name": "scheduler", "running": True}]},
        backup_manifest={"items": [{"name": "data", "exists": True}]},
        notification_configured=False,
        manual_order_ready=False,
        broker_auto_trading_enabled=True,
    )

    failures = {item["name"]: item for item in report["checks"] if item["status"] == "FAIL"}
    assert report["status"] == "NOT_READY"
    assert failures["broker_permission_boundary"]["message"] == "券商自动交易开关已开启，当前阶段禁止自动下单"
