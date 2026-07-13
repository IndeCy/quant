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
from data.tushare_beta_incremental import BetaIncrementalStore, TushareBetaProClient, TushareBetaUpdater
from pipeline.production_daily import write_run_log
from runtime.config import get_config_value
from runtime.mainline_cache_sync import sync_mainline_cache_from_increment
from runtime.hot_money_limit_cache_pipeline import resolve_hot_money_cache_dates, update_hot_money_limit_cache
from runtime.opportunity_catalog import register_builtin_opportunity_themes
from runtime.paths import get_runtime_paths
from runtime.repository import SystemRepository


def main(trade_date: str | None = None) -> None:
    """更新 A 股行情、ETF/指数基准并校验复权因子完整性。"""
    paths = get_runtime_paths()
    paths.ensure_directories()
    run_date = trade_date or datetime.now().strftime("%Y%m%d")
    run_dir = paths.runs_dir / run_date
    repository = SystemRepository(paths.system_state_path)
    register_builtin_opportunity_themes(repository)
    try:
        updated_dates, warnings = update_incremental(run_date)
        warnings.extend(update_benchmark_incremental(run_date))
        warnings.append(_update_beta_incremental(paths, run_date))
        if _has_blocking_update_warning(warnings):
            raise RuntimeError("; ".join(warnings))
        validate_incremental_quality()
        sync_result = sync_mainline_cache_from_increment(
            paths,
            account_id=None,
            requested_date=datetime.strptime(run_date, "%Y%m%d").date(),
            cache_path=paths.data_dir / "market_cache.sqlite3",
            extra_stock_symbols=_opportunity_symbols(repository),
        )
        if sync_result.missing_symbols:
            raise RuntimeError(f"主线链动缓存同步失败，缺失标的: {', '.join(sync_result.missing_symbols[:20])}")
        warnings.append(f"主线链动缓存已同步: 写入{sync_result.rows_written}行")
        _append_hot_money_cache_message(paths, updated_dates, warnings)
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


def _append_hot_money_cache_message(paths, updated_dates: list[str], warnings: list[str]) -> list[str]:
    """同步游资涨跌停缓存，并追加到数据更新摘要。"""
    cache_dates = resolve_hot_money_cache_dates(paths, updated_dates)
    result = update_hot_money_limit_cache(paths, cache_dates)
    if result["updated_dates"]:
        warnings.append(f"游资涨跌停缓存已同步: 写入{result['rows_written']}行")
    else:
        warnings.append("游资涨跌停缓存：已是最新，无新增交易日")
    return warnings


def _update_beta_incremental(paths, run_date: str) -> str:
    """补充 Market Beta V1 所需 P0 数据，失败时记录但不阻断策略。"""
    token = get_config_value("TUSHARE_TOKEN")
    if not token:
        return "Beta扩展数据未更新: 缺少TUSHARE_TOKEN"
    try:
        store = BetaIncrementalStore(paths.beta_increment_path)
        updater = TushareBetaUpdater(TushareBetaProClient(token), store, fund_symbols=["510300.SH"])
        result = updater.update(run_date)
        rows = (
            result.daily_basic_rows
            + result.index_dailybasic_rows
            + result.fund_share_rows
            + result.moneyflow_hsgt_rows
            + result.margin_rows
            + result.margin_detail_rows
        )
        return f"Beta扩展数据已同步: 写入{rows}行"
    except Exception as exc:
        return f"Beta扩展数据未更新: {exc}"


def _opportunity_symbols(repository: SystemRepository) -> list[str]:
    """读取所有机会观察池股票，确保每日研究排行有行情输入。"""
    symbols: list[str] = []
    for theme in repository.list_opportunity_themes():
        symbols.extend(str(stock["symbol"]) for stock in theme.get("stocks", []))
    return sorted(set(symbols))


if __name__ == "__main__":
    raise SystemExit("请使用 scripts/run_daily_pipeline.py 执行完整原子流水线")
