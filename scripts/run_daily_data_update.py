#!/usr/bin/env python3
"""执行每日统一数据更新，供后续策略任务只读使用。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.run_quality_overlay_paper import (
    _has_blocking_update_warning,
    update_benchmark_incremental,
    update_incremental,
    validate_incremental_quality,
)
from pipeline.production_daily import write_run_log
from runtime.paths import get_runtime_paths
from runtime.repository import SystemRepository


def main() -> None:
    """更新 A 股行情、ETF/指数基准并校验复权因子完整性。"""
    paths = get_runtime_paths()
    paths.ensure_directories()
    run_date = datetime.now().strftime("%Y%m%d")
    run_dir = paths.runs_dir / run_date
    repository = SystemRepository(paths.system_state_path)
    try:
        updated_dates, warnings = update_incremental(run_date)
        warnings.extend(update_benchmark_incremental(run_date))
        if _has_blocking_update_warning(warnings):
            raise RuntimeError("; ".join(warnings))
        validate_incremental_quality()
        message = _build_success_message(updated_dates, warnings)
        write_run_log(run_dir, "SUCCESS", message)
        repository.record_strategy_run("system_data_update", run_date, "SUCCESS", run_dir, message)
        repository.record_run_step(
            "system_data_update",
            run_date,
            1,
            "data_update",
            "SUCCESS",
            message,
            run_dir,
        )
        print(message)
    except Exception as exc:
        write_run_log(run_dir, "FAILED", str(exc))
        repository.record_strategy_run("system_data_update", run_date, "FAILED", run_dir, str(exc))
        raise


def _build_success_message(updated_dates: list[str], warnings: list[str]) -> str:
    """把数据更新结果压缩成调度日志可读摘要。"""
    parts = [f"A股新增交易日 {len(updated_dates)} 个"]
    if updated_dates:
        parts.append(f"最新 {updated_dates[-1]}")
    if warnings:
        parts.append("; ".join(warnings))
    return "，".join(parts)


if __name__ == "__main__":
    main()
