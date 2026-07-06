"""统一每日交易流水线。

调度、手动补跑和 API 触发都必须经过这里，避免出现不同入口行为不一致。
"""

from __future__ import annotations

import contextlib
from datetime import datetime
import io
from typing import Any

from monitoring.repository import MonitoringRepository
from runtime.data_quality_gate import run_data_quality_gate
from runtime.notification_config import NotificationResult, send_bark_notification
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.strategy_batch_runner import run_enabled_strategy_instances


PIPELINE_STRATEGY_ID = "daily_trading_pipeline"


def run_production_daily_pipeline(
    paths: RuntimePaths | None = None,
    push: bool = False,
    source: str = "manual",
) -> dict[str, object]:
    """执行每日原子流水线：数据更新成功后才运行策略批处理。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    repository = SystemRepository(runtime_paths.system_state_path)
    trade_date = datetime.now().strftime("%Y%m%d")
    run_dir = runtime_paths.runs_dir / trade_date
    run_dir.mkdir(parents=True, exist_ok=True)

    repository.record_strategy_run(PIPELINE_STRATEGY_ID, trade_date, "RUNNING", run_dir, f"source={source}")
    try:
        data_message = run_data_update()
        repository.record_run_step(
            PIPELINE_STRATEGY_ID,
            trade_date,
            1,
            "data_update",
            "SUCCESS",
            data_message,
            run_dir,
        )
        _notify_data_update(repository, trade_date, run_dir, push, "SUCCESS", data_message)
    except Exception as exc:
        message = f"数据更新失败，策略未执行: {exc}"
        repository.record_run_step(PIPELINE_STRATEGY_ID, trade_date, 1, "data_update", "FAILED", str(exc), run_dir)
        _notify_data_update(repository, trade_date, run_dir, push, "FAILED", str(exc))
        notification = _notify_if_needed(repository, trade_date, run_dir, push, "FAILED", message)
        repository.record_strategy_run(PIPELINE_STRATEGY_ID, trade_date, "FAILED", run_dir, _with_notification(message, notification))
        raise

    try:
        quality_result = run_data_quality_gate(runtime_paths)
        if quality_result["status"] != "PASS":
            raise RuntimeError(_summarize_quality_gate(quality_result))
        repository.record_run_step(
            PIPELINE_STRATEGY_ID,
            trade_date,
            3,
            "data_quality_gate",
            "SUCCESS",
            _summarize_quality_gate(quality_result),
            run_dir,
        )
    except Exception as exc:
        message = f"数据质量门禁失败，策略未执行: {exc}"
        repository.record_run_step(
            PIPELINE_STRATEGY_ID,
            trade_date,
            3,
            "data_quality_gate",
            "FAILED",
            str(exc),
            run_dir,
        )
        notification = _notify_if_needed(repository, trade_date, run_dir, push, "FAILED", message)
        repository.record_strategy_run(PIPELINE_STRATEGY_ID, trade_date, "FAILED", run_dir, _with_notification(message, notification))
        raise

    try:
        strategy_summary = run_strategy_batch(runtime_paths, push=False)
        strategy_status = "SUCCESS" if int(strategy_summary.get("failed_count", 0)) == 0 else "FAILED"
        strategy_message = _summarize_strategy_batch(strategy_summary)
        repository.record_run_step(
            PIPELINE_STRATEGY_ID,
            trade_date,
            4,
            "strategy_batch",
            strategy_status,
            strategy_message,
            run_dir,
        )
        if strategy_status != "SUCCESS":
            raise RuntimeError(strategy_message)
    except Exception as exc:
        message = f"策略批处理失败: {exc}"
        notification = _notify_if_needed(repository, trade_date, run_dir, push, "FAILED", message)
        repository.record_strategy_run(PIPELINE_STRATEGY_ID, trade_date, "FAILED", run_dir, _with_notification(message, notification))
        raise

    message = _build_operation_summary(runtime_paths, strategy_summary)
    notification = _notify_if_needed(repository, trade_date, run_dir, push, "SUCCESS", message)
    repository.record_strategy_run(PIPELINE_STRATEGY_ID, trade_date, "SUCCESS", run_dir, _with_notification(message, notification))
    return {
        "trade_date": trade_date,
        "status": "SUCCESS",
        "source": source,
        "data_update": data_message,
        "strategy_batch": strategy_summary,
        "notification": notification.__dict__,
    }


def run_data_update() -> str:
    """运行统一数据更新脚本，供测试替换。"""
    from scripts.run_daily_data_update import main as data_update_main

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        data_update_main()
    return output.getvalue().strip().splitlines()[-1] if output.getvalue().strip() else "data update completed"


def run_strategy_batch(paths: RuntimePaths, push: bool = False) -> dict[str, object]:
    """运行所有启用策略实例，通知由本流水线统一发送。"""
    return run_enabled_strategy_instances(paths=paths, push=push)


def _notify_if_needed(
    repository: SystemRepository,
    trade_date: str,
    run_dir: object,
    push: bool,
    status: str,
    message: str,
) -> NotificationResult:
    """按需发送流水线级通知，并把结果写入步骤日志。"""
    if push:
        result = send_bark_notification(f"量化每日流水线{status}", message)
    else:
        result = NotificationResult("SKIPPED", "未开启push")
    repository.record_run_step(
        PIPELINE_STRATEGY_ID,
        trade_date,
        5,
        "notification",
        result.status,
        result.message,
        run_dir,
    )
    return result


def _notify_data_update(
    repository: SystemRepository,
    trade_date: str,
    run_dir: object,
    push: bool,
    status: str,
    message: str,
) -> NotificationResult:
    """数据更新使用独立 Bark 模板，先于策略通知。"""
    body = "\n".join(
        [
            f"数据更新状态：{status}",
            f"交易日：{trade_date}",
            *_format_data_update_lines(message),
            f"策略执行：{'数据成功后继续执行' if status == 'SUCCESS' else '已阻断，策略未执行'}",
        ]
    )
    result = send_bark_notification(f"量化数据更新{status}", body) if push else NotificationResult("SKIPPED", "未开启push")
    repository.record_run_step(
        PIPELINE_STRATEGY_ID,
        trade_date,
        2,
        "data_notification",
        result.status,
        result.message,
        run_dir,
    )
    return result


def _format_data_update_lines(message: str) -> list[str]:
    """把底层更新摘要转换成 Bark 可读文案。"""
    lines: list[str] = []
    if "A股新增交易日 0 个" in message:
        lines.append("A股日线：已是最新，无新增交易日")
    elif "A股新增交易日" in message:
        part = message.split("，", 1)[0]
        lines.append(f"A股日线：{part.replace('A股', '')}")
    if "最新 " in message:
        latest = message.split("最新 ", 1)[1].split("，", 1)[0].split(";", 1)[0]
        lines.append(f"最新交易日：{latest}")
    if "ETF/指数基准已更新" in message:
        benchmark = message.split("ETF/指数基准已更新:", 1)[1].split(";", 1)[0].split("，", 1)[0].strip()
        lines.append(f"基准数据：已更新 {benchmark}")
    if "主线链动缓存已同步" in message:
        cache = message.split("主线链动缓存已同步:", 1)[1].split("，", 1)[0].strip()
        lines.append(f"主线链动缓存：{cache}")
    if not lines:
        lines.append(f"摘要：{message}")
    return lines


def _summarize_strategy_batch(summary: dict[str, object]) -> str:
    """压缩策略批处理结果，便于 Bark 和运行中心展示。"""
    results = summary.get("results", [])
    detail = []
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                detail.append(f"{item.get('strategy_id')}={item.get('status')}")
    head = (
        f"enabled={summary.get('enabled_count', 0)}, "
        f"success={summary.get('success_count', 0)}, failed={summary.get('failed_count', 0)}"
    )
    return head if not detail else f"{head}; " + ", ".join(detail)


def _summarize_quality_gate(result: dict[str, object]) -> str:
    """压缩数据质量门禁结果，便于运行中心展示。"""
    failed_count = int(result.get("failed_count", 0))
    check_count = int(result.get("check_count", 0))
    if failed_count == 0:
        return f"PASS: {check_count} checks"
    failed = []
    for item in result.get("checks", []):
        if isinstance(item, dict) and item.get("status") == "FAIL":
            failed.append(f"{item.get('dataset_id')}.{item.get('table_name')}: {item.get('message')}")
    return f"FAIL: {failed_count}/{check_count}; " + "; ".join(failed)


def _build_operation_summary(paths: RuntimePaths, summary: dict[str, object]) -> str:
    """生成 Bark 和运行记录共用的每日操作摘要。"""
    failed_count = int(summary.get("failed_count", 0))
    enabled_count = int(summary.get("enabled_count", 0))
    success_count = int(summary.get("success_count", 0))
    lines = [
        f"运行状态：{success_count}/{enabled_count} 成功",
        f"是否需要操作：{'是，存在失败策略需检查' if failed_count else '否'}",
        "",
    ]
    monitoring = MonitoringRepository(paths.monitoring_path)
    for item in summary.get("results", []):
        if not isinstance(item, dict):
            continue
        strategy_id = str(item.get("strategy_id", ""))
        latest = monitoring.load_latest_strategy_metrics(strategy_id)
        if latest is None:
            lines.extend([f"{strategy_id}", f"- 运行状态：{item.get('status')}", ""])
            continue
        lines.extend(_format_strategy_operation_block(latest))
        lines.append("")
    return "\n".join(lines).strip()


def _format_strategy_operation_block(metrics: dict[str, object]) -> list[str]:
    """把任意策略最新监控指标格式化成统一关注字段。"""
    volatility = float(metrics.get("volatility_20", 0.0))
    drawdown = float(metrics.get("drawdown", 0.0))
    if str(metrics.get("strategy_id") or "").endswith("_observer_v0"):
        return [
            str(metrics.get("strategy_name") or metrics.get("strategy_id")),
            "- 状态：观察策略，不构成调仓建议",
            f"- 观察仓位：{float(metrics.get('exposure', 0.0)):.2%}",
            f"- 当日收益：{float(metrics.get('daily_return', 0.0)):.2%}",
            f"- 当前回撤：{drawdown:.2%}",
            "- 操作建议：不操作",
        ]
    return [
        str(metrics.get("strategy_name") or metrics.get("strategy_id")),
        f"- 仓位：{float(metrics.get('exposure', 0.0)):.2%}",
        f"- 当日收益：{float(metrics.get('daily_return', 0.0)):.2%}",
        f"- 当前回撤：{drawdown:.2%}",
        f"- 20日波动率：{volatility:.2%}",
        f"- 风险状态：{_operation_risk_state(volatility, drawdown)}",
        f"- 成交失败：{int(metrics.get('failed_order_count', 0))}",
    ]


def _operation_risk_state(volatility_20: float, drawdown: float) -> str:
    """统一操作摘要风险标签，优先提示高波动和深回撤。"""
    if volatility_20 >= 0.50 or drawdown <= -0.20:
        return "HIGH_VOL"
    if volatility_20 >= 0.35 or drawdown <= -0.10:
        return "ELEVATED"
    return "NORMAL"


def _with_notification(message: str, notification: NotificationResult) -> str:
    """把通知状态拼入主运行记录，避免排查时只能看子步骤。"""
    return f"{message}; notification={notification.status}:{notification.message}"
