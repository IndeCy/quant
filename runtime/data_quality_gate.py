"""生产数据质量门禁。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.data_catalog_runner import refresh_data_catalog
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


class DataQualityError(RuntimeError):
    """数据质量门禁失败。"""


@dataclass(frozen=True)
class DataQualityRule:
    """关键数据源检查规则。"""

    dataset_id: str
    required_tables: tuple[str, ...]
    min_trade_date: str = ""


DEFAULT_RULES = [
    DataQualityRule("live_market_increment_duckdb", ("daily", "adj_factor")),
    DataQualityRule("benchmark_increment_duckdb", ("fund_daily", "fund_adj", "index_daily")),
]


def run_data_quality_gate(
    paths: RuntimePaths | None = None,
    rules: list[DataQualityRule] | None = None,
    min_trade_date: str = "",
    raise_on_fail: bool = False,
) -> dict[str, Any]:
    """刷新数据目录并执行关键数据质量检查。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    refresh_data_catalog(paths=runtime_paths)
    repository = SystemRepository(runtime_paths.system_state_path)
    active_rules = [
        DataQualityRule(rule.dataset_id, rule.required_tables, rule.min_trade_date or min_trade_date)
        for rule in (rules or DEFAULT_RULES)
    ]
    checks: list[dict[str, Any]] = []
    for rule in active_rules:
        checks.extend(_evaluate_rule(repository, rule))
    failed = [item for item in checks if item["status"] == "FAIL"]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "check_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
    }
    if failed and raise_on_fail:
        raise DataQualityError(_format_failure_message(failed))
    return result


def _evaluate_rule(repository: SystemRepository, rule: DataQualityRule) -> list[dict[str, Any]]:
    """检查单个数据源和表级日期。"""
    source = repository.load_data_source(rule.dataset_id)
    if source is None:
        return [_check(rule.dataset_id, "", "FAIL", "关键数据源缺失")]
    if source["status"] != "OK":
        return [_check(rule.dataset_id, "", "FAIL", f"数据源状态异常: {source['status']}")]
    tables = {str(item["table_name"]): item for item in source.get("tables", [])}
    checks: list[dict[str, Any]] = []
    for table_name in rule.required_tables:
        table = tables.get(table_name)
        if table is None:
            checks.append(_check(rule.dataset_id, table_name, "FAIL", f"关键表缺失: {table_name}"))
            continue
        latest_date = _normalize_date(str(table.get("latest_date") or ""))
        min_date = _normalize_date(rule.min_trade_date)
        if min_date and latest_date and latest_date < min_date:
            checks.append(
                _check(
                    rule.dataset_id,
                    table_name,
                    "FAIL",
                    f"{table_name} 最新日期 {table.get('latest_date')} 早于要求日期 {rule.min_trade_date}",
                    table.get("latest_date", ""),
                )
            )
        elif min_date and not latest_date:
            checks.append(_check(rule.dataset_id, table_name, "FAIL", f"{table_name} 缺少日期字段或最新日期"))
        else:
            checks.append(_check(rule.dataset_id, table_name, "PASS", "OK", table.get("latest_date", "")))
    return checks


def _check(
    dataset_id: str,
    table_name: str,
    status: str,
    message: str,
    latest_date: str = "",
) -> dict[str, Any]:
    """生成固定结构检查结果。"""
    return {
        "dataset_id": dataset_id,
        "table_name": table_name,
        "status": status,
        "latest_date": latest_date,
        "message": message,
    }


def _normalize_date(value: str) -> str:
    """统一比较 YYYYMMDD 和 YYYY-MM-DD 日期字符串。"""
    return value.replace("-", "")[:8] if value else ""


def _format_failure_message(failed: list[dict[str, Any]]) -> str:
    """压缩失败信息，便于流水线日志和 Bark 展示。"""
    return "; ".join(f"{item['dataset_id']}.{item['table_name']}: {item['message']}" for item in failed)
