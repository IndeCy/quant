"""生产候选运行就绪度汇总。"""

from __future__ import annotations

from typing import Any


def build_readiness_report(
    token_present: bool,
    data_health: dict[str, Any],
    scheduler_status: dict[str, Any],
    service_status: dict[str, Any],
) -> dict[str, Any]:
    """汇总生产候选系统是否具备每日自动运行条件。"""
    checks = [
        _check("tushare_token", token_present, "Tushare token 已配置", "缺少 TUSHARE_TOKEN"),
        _check_data_pair("live_market_data", data_health.get("live_market_increment", {}), "latest_daily_date", "latest_adj_factor_date"),
        _check_data_pair("benchmark_data", data_health.get("benchmark_increment", {}), "latest_fund_date", "latest_fund_adj_date"),
        _check("monitoring_db", bool(data_health.get("monitoring", {}).get("exists")), "监控库存在", "监控库缺失"),
        _check("system_state_db", bool(data_health.get("system_state", {}).get("exists")), "系统状态库存在", "系统状态库缺失"),
        _check("scheduler_job", bool(scheduler_status.get("enabled")), "每日任务已登记", "每日任务未登记"),
    ]
    service_map = {item.get("name"): bool(item.get("running")) for item in service_status.get("services", [])}
    checks.append(_check("api_service", service_map.get("api", False), "API 服务运行中", "API 服务未运行"))
    checks.append(_check("frontend_service", service_map.get("frontend", False), "前端服务运行中", "前端服务未运行"))
    checks.append(_check("scheduler_service", service_map.get("scheduler", False), "调度器运行中", "调度器未运行"))
    return {
        "status": "READY" if all(item["status"] == "PASS" for item in checks) else "NOT_READY",
        "checks": checks,
    }


def _check(name: str, passed: bool, pass_message: str, fail_message: str) -> dict[str, str]:
    return {"name": name, "status": "PASS" if passed else "FAIL", "message": pass_message if passed else fail_message}


def _check_data_pair(section_name: str, section: dict[str, Any], first_key: str, second_key: str) -> dict[str, str]:
    exists = bool(section.get("exists"))
    first = section.get(first_key)
    second = section.get(second_key)
    passed = exists and bool(first) and first == second
    message = f"数据日期一致: {first}" if passed else f"数据缺失或日期不一致: {first or '-'} / {second or '-'}"
    return {"name": section_name, "status": "PASS" if passed else "FAIL", "message": message}
