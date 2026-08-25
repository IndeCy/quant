"""在唯一日常 Pipeline 内增量维护研究扩展数据。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from data.block_trades import update_block_trade_cache
from data.holder_trades import update_holder_trade_cache
from data.margin_trades import update_margin_trade_cache
from data.order_flow import TushareOrderFlowClient, update_order_flow_cache
from data.shareholder_count import update_shareholder_count_cache
from data.top_inst import TushareTopInstClient, update_top_inst_cache
from runtime.data_sync_repository import DataSyncRepository
from runtime.paths import RuntimePaths


MAX_GAP_DATES_PER_RUN = 5
EVENT_LOOKBACK_DAYS = 62
TRIGGER_SOURCE = "daily_trading_pipeline:data_update"


@dataclass(frozen=True)
class ExtensionDataClients:
    """可注入的外部客户端集合，生产使用 Tushare，测试使用本地替身。"""

    order_flow: Any
    top_inst: Any
    margin_detail: Any
    block_trade: Any
    shareholder_count: Any
    holder_trade: Any


@dataclass(frozen=True)
class DataDomainSyncResult:
    """单个研究数据域的日更摘要。"""

    dataset_id: str
    status: str
    requested_start: str
    requested_end: str
    fetched_rows: int = 0
    stored_rows: int = 0
    message: str = ""


@dataclass(frozen=True)
class _OperationResult:
    fetched_rows: int
    stored_rows: int
    success: bool = True
    message: str = ""


def create_tushare_extension_clients(token: str) -> ExtensionDataClients:
    """创建共享凭据的生产客户端，凭据本身不进入日志或运行结果。"""
    if not token.strip():
        raise ValueError("TUSHARE_TOKEN 不能为空")
    import tushare as ts

    pro = ts.pro_api(token)
    return ExtensionDataClients(
        order_flow=TushareOrderFlowClient(token),
        top_inst=TushareTopInstClient(token),
        margin_detail=pro,
        block_trade=pro,
        shareholder_count=pro,
        holder_trade=pro,
    )


def sync_daily_extension_data(
    paths: RuntimePaths,
    run_date: str,
    token: str,
    *,
    clients: ExtensionDataClients | None = None,
    repository: DataSyncRepository | None = None,
    max_gap_dates: int = MAX_GAP_DATES_PER_RUN,
) -> tuple[DataDomainSyncResult, ...]:
    """同步资金流、龙虎榜、两融和公告事件，不改变核心行情门禁。"""
    normalized_date = _normalize_date(run_date)
    if max_gap_dates <= 0:
        raise ValueError("max_gap_dates 必须为正")
    paths.ensure_directories()
    resolved_clients = clients or create_tushare_extension_clients(token)
    sync_repository = repository or DataSyncRepository(paths.system_state_path)

    results = [
        _sync_order_flow(
            paths,
            normalized_date,
            resolved_clients.order_flow,
            sync_repository,
            max_gap_dates,
        ),
        _sync_top_inst(
            paths,
            normalized_date,
            resolved_clients.top_inst,
            sync_repository,
            max_gap_dates,
        ),
        _sync_margin_detail(
            paths,
            normalized_date,
            resolved_clients.margin_detail,
            sync_repository,
            max_gap_dates,
        ),
        _sync_block_trades(paths, normalized_date, resolved_clients.block_trade, sync_repository),
        _sync_shareholder_count(paths, normalized_date, resolved_clients.shareholder_count, sync_repository),
        _sync_holder_trades(paths, normalized_date, resolved_clients.holder_trade, sync_repository),
    ]
    return tuple(results)


def format_extension_sync_summary(results: tuple[DataDomainSyncResult, ...]) -> str:
    """把多数据域结果压缩为调度日志和 Bark 可读的一行。"""
    succeeded = [item for item in results if item.status == "SUCCESS"]
    skipped = [item for item in results if item.status == "SKIPPED"]
    failed = [item for item in results if item.status == "FAILED"]
    parts = [f"更新{len(succeeded)}域/抓取{sum(item.fetched_rows for item in succeeded)}行"]
    if skipped:
        parts.append(f"{len(skipped)}域已是最新")
    if failed:
        names = ",".join(item.dataset_id for item in failed)
        parts.append(f"{len(failed)}域未更新({names})")
    return "研究扩展数据增量: " + "，".join(parts)


def _sync_order_flow(
    paths: RuntimePaths,
    run_date: str,
    client: Any,
    repository: DataSyncRepository,
    max_gap_dates: int,
) -> DataDomainSyncResult:
    dates = resolve_missing_market_dates(
        paths,
        paths.order_flow_path,
        "order_flow_sync_log",
        run_date,
        max_gap_dates=max_gap_dates,
    )
    if not dates:
        return _skipped("flow.order", run_date)

    def operation() -> _OperationResult:
        result = update_order_flow_cache(client, paths.order_flow_path, dates)
        return _OperationResult(
            fetched_rows=result.fetched_rows,
            stored_rows=result.stored_rows,
            success=result.success,
            message=_failed_dates_message(result.failed_dates),
        )

    return _run_recorded(repository, "flow.order", dates[0], dates[-1], operation)


def _sync_top_inst(
    paths: RuntimePaths,
    run_date: str,
    client: Any,
    repository: DataSyncRepository,
    max_gap_dates: int,
) -> DataDomainSyncResult:
    dates = resolve_missing_market_dates(
        paths,
        paths.top_inst_path,
        "top_inst_sync_log",
        run_date,
        max_gap_dates=max_gap_dates,
    )
    if not dates:
        return _skipped("flow.top_inst", run_date)

    def operation() -> _OperationResult:
        result = update_top_inst_cache(client, paths.top_inst_path, dates)
        return _OperationResult(
            fetched_rows=result.fetched_rows,
            stored_rows=result.stored_rows,
            success=result.success,
            message=_failed_dates_message(result.failed_dates),
        )

    return _run_recorded(repository, "flow.top_inst", dates[0], dates[-1], operation)


def _sync_margin_detail(
    paths: RuntimePaths,
    run_date: str,
    client: Any,
    repository: DataSyncRepository,
    max_gap_dates: int,
) -> DataDomainSyncResult:
    dates = resolve_missing_market_dates(
        paths,
        paths.margin_trade_path,
        "margin_sync_log",
        run_date,
        max_gap_dates=max_gap_dates,
    )
    if not dates:
        return _skipped("margin.detail", run_date)

    def operation() -> _OperationResult:
        result = update_margin_trade_cache(client, paths.margin_trade_path, dates)
        return _OperationResult(
            fetched_rows=result.fetched_rows,
            stored_rows=_table_row_count(paths.margin_trade_path, "margin_detail"),
            success=result.success,
            message=_failed_dates_message(result.failed_dates),
        )

    return _run_recorded(repository, "margin.detail", dates[0], dates[-1], operation)


def _sync_block_trades(
    paths: RuntimePaths,
    run_date: str,
    client: Any,
    repository: DataSyncRepository,
) -> DataDomainSyncResult:
    dataset_id = "event.block_trade"
    if _last_event_sync_end(paths.block_trade_path, "block_trade_sync_state") >= run_date:
        return _skipped(dataset_id, run_date)
    start_date = _event_lookback_start(run_date)

    def operation() -> _OperationResult:
        result = update_block_trade_cache(
            client,
            paths.block_trade_path,
            start_date=start_date,
            end_date=run_date,
        )
        return _OperationResult(result.fetched_rows, result.stored_rows)

    return _run_recorded(repository, dataset_id, start_date, run_date, operation)


def _sync_shareholder_count(
    paths: RuntimePaths,
    run_date: str,
    client: Any,
    repository: DataSyncRepository,
) -> DataDomainSyncResult:
    dataset_id = "event.shareholder_count"
    if _last_event_sync_end(paths.shareholder_count_path, "shareholder_sync_state") >= run_date:
        return _skipped(dataset_id, run_date)
    start_date = _event_lookback_start(run_date)

    def operation() -> _OperationResult:
        result = update_shareholder_count_cache(
            client,
            paths.shareholder_count_path,
            start_date=start_date,
            end_date=run_date,
        )
        return _OperationResult(result.fetched_rows, result.stored_rows)

    return _run_recorded(repository, dataset_id, start_date, run_date, operation)


def _sync_holder_trades(
    paths: RuntimePaths,
    run_date: str,
    client: Any,
    repository: DataSyncRepository,
) -> DataDomainSyncResult:
    dataset_id = "event.holder_trade"
    if _last_event_sync_end(paths.holder_trade_path, "holder_trade_sync_state") >= run_date:
        return _skipped(dataset_id, run_date)
    start_date = _event_lookback_start(run_date)

    def operation() -> _OperationResult:
        result = update_holder_trade_cache(
            client,
            paths.holder_trade_path,
            start_date=start_date,
            end_date=run_date,
        )
        return _OperationResult(result.fetched_rows, result.stored_rows)

    return _run_recorded(repository, dataset_id, start_date, run_date, operation)


def resolve_missing_market_dates(
    paths: RuntimePaths,
    cache_path: Path,
    sync_table: str,
    run_date: str,
    *,
    max_gap_dates: int = MAX_GAP_DATES_PER_RUN,
) -> list[str]:
    """最新日优先保留，同时按时间顺序逐日消化历史缺口。"""
    if max_gap_dates <= 0:
        raise ValueError("max_gap_dates 必须为正")
    live_dates = _live_market_dates(paths, run_date)
    completed = _completed_dates(cache_path, sync_table)
    missing = sorted(live_dates - completed)
    if len(missing) <= max_gap_dates:
        return missing
    if max_gap_dates == 1:
        return [missing[-1]]
    return sorted([*missing[: max_gap_dates - 1], missing[-1]])


def _run_recorded(
    repository: DataSyncRepository,
    dataset_id: str,
    start_date: str,
    end_date: str,
    operation: Callable[[], _OperationResult],
) -> DataDomainSyncResult:
    sync_id = repository.start_run(dataset_id, start_date, end_date, TRIGGER_SOURCE)
    try:
        result = operation()
        status = "SUCCESS" if result.success else "FAILED"
        repository.finish_run(
            sync_id,
            status,
            fetched_rows=result.fetched_rows,
            stored_rows=result.stored_rows,
            message=result.message,
        )
        return DataDomainSyncResult(
            dataset_id,
            status,
            start_date,
            end_date,
            result.fetched_rows,
            result.stored_rows,
            result.message,
        )
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:2000]
        repository.finish_run(sync_id, "FAILED", message=message)
        return DataDomainSyncResult(dataset_id, "FAILED", start_date, end_date, message=message)


def _skipped(dataset_id: str, run_date: str) -> DataDomainSyncResult:
    return DataDomainSyncResult(dataset_id, "SKIPPED", run_date, run_date, message="已是最新")


def _live_market_dates(paths: RuntimePaths, run_date: str) -> set[str]:
    if not paths.live_market_increment_path.exists():
        return set()
    with duckdb.connect(str(paths.live_market_increment_path), read_only=True) as con:
        tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
        if "daily" not in tables:
            return set()
        rows = con.execute(
            "SELECT DISTINCT trade_date FROM daily WHERE trade_date IS NOT NULL AND trade_date <= ?",
            [run_date],
        ).fetchall()
    return {str(row[0]) for row in rows}


def _completed_dates(cache_path: Path, sync_table: str) -> set[str]:
    _validate_identifier(sync_table)
    if not cache_path.exists():
        return set()
    with duckdb.connect(str(cache_path), read_only=True) as con:
        tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
        if sync_table not in tables:
            return set()
        rows = con.execute(
            f'SELECT trade_date FROM "{sync_table}" WHERE status = ?',
            ["SUCCESS"],
        ).fetchall()
    return {str(row[0]) for row in rows}


def _last_event_sync_end(cache_path: Path, state_table: str) -> str:
    _validate_identifier(state_table)
    if not cache_path.exists():
        return ""
    with duckdb.connect(str(cache_path), read_only=True) as con:
        tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
        if state_table not in tables:
            return ""
        row = con.execute(f'SELECT MAX(last_requested_end_date) FROM "{state_table}"').fetchone()
    return str(row[0] or "")


def _table_row_count(cache_path: Path, table_name: str) -> int:
    _validate_identifier(table_name)
    with duckdb.connect(str(cache_path), read_only=True) as con:
        return int(con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])


def _event_lookback_start(run_date: str) -> str:
    value = datetime.strptime(run_date, "%Y%m%d") - timedelta(days=EVENT_LOOKBACK_DAYS)
    return value.strftime("%Y%m%d")


def _failed_dates_message(failed_dates: tuple[str, ...]) -> str:
    return "" if not failed_dates else f"未完成日期: {','.join(failed_dates)}"


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("run_date 必须是有效 YYYYMMDD") from exc
    return normalized


def _validate_identifier(value: str) -> None:
    if not value or not value.replace("_", "").isalnum() or value[0].isdigit():
        raise ValueError(f"非法表名: {value}")
