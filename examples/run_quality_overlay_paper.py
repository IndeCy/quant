"""运行冻结的 Quality Cleanup + 20日波动率风险层 Paper 策略。"""

from __future__ import annotations

import argparse
from datetime import datetime
import math
import os
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.notifier import NotificationMessage, build_notifier
from backtest.quality_overlay_paper import QualityPaperSnapshot, QualityPaperStore, build_target_weights
from backtest.research_benchmark import load_hs300_benchmark
from data.live_market_view import open_live_market_connection
from data.tushare_benchmark_incremental import (
    BenchmarkIncrementalStore,
    TushareBenchmarkProClient,
    TushareBenchmarkUpdater,
)
from data.tushare_incremental import IncrementalDuckDBStore, TushareDailyUpdater, TushareProClient
from examples.quality_cleanup_audit import (
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_risk_layer_research import run_risk_layer_backtest
from examples.quality_strategy_v1 import DB_PATH, FUND_BASIC_PATH, FUND_DAILY_PATH, attach_financial_dbs, create_signal_date_table
from examples.strategy_comparison_research import create_feature_table, load_calendar, load_research_bars, load_signal_dates
from monitoring.dashboard_data import build_dashboard_payload, write_dashboard_files
from monitoring.metrics import build_market_monitor_frame, build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from pipeline.production_daily import build_monthly_review, is_month_end_trade_date, write_daily_artifacts, write_run_log
from runtime.paths import get_runtime_paths
from runtime.repository import SystemRepository
from runtime.strategy_catalog import register_quality_alpha_v1


RUNTIME_PATHS = get_runtime_paths()
INCREMENT_PATH = RUNTIME_PATHS.live_market_increment_path
BENCHMARK_INCREMENT_PATH = RUNTIME_PATHS.benchmark_increment_path
PAPER_PATH = RUNTIME_PATHS.quality_overlay_paper_path
MONITORING_PATH = RUNTIME_PATHS.monitoring_path
REPORT_PATH = RUNTIME_PATHS.latest_report_path
DASHBOARD_JSON_PATH = RUNTIME_PATHS.dashboard_json_path
DASHBOARD_HTML_PATH = RUNTIME_PATHS.dashboard_html_path
RUNS_ROOT = RUNTIME_PATHS.runs_dir
VOL_WINDOW = 20
VOL_THRESHOLD = 0.45
REDUCED_EXPOSURE = 0.30


def update_incremental(end_date: str) -> tuple[list[str], list[str]]:
    """补齐日线增量，接口受限时保留最后完整缓存并告警。"""
    warnings: list[str] = []
    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        return [], ["未检测到TUSHARE_TOKEN，本次未更新行情"]
    import duckdb

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        base_latest = str(con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])
    store = IncrementalDuckDBStore(INCREMENT_PATH)
    updater = TushareDailyUpdater(TushareProClient(token), store, base_latest)
    try:
        result = updater.update_through(end_date)
        return result.updated_dates, warnings
    except Exception as exc:  # 外部权限和频控不能破坏已有Paper快照。
        warnings.append(f"Tushare增量更新失败: {exc}")
        return [], warnings


def update_benchmark_incremental(end_date: str) -> list[str]:
    """补齐510300 ETF和上证指数基准缓存。"""
    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        return ["未检测到TUSHARE_TOKEN，本次未更新ETF/指数基准"]
    store = BenchmarkIncrementalStore(BENCHMARK_INCREMENT_PATH)
    updater = TushareBenchmarkUpdater(TushareBenchmarkProClient(token), store)
    try:
        result = updater.update(
            end_date=end_date,
            fund_base_latest={"510300.SH": _latest_etf_base_date("510300.SH")},
            index_base_latest={"000001.SH": _latest_index_base_date("000001.SH")},
        )
    except Exception as exc:
        return [f"Tushare ETF/指数基准更新失败: {exc}"]
    if result.updated_symbols:
        return [f"ETF/指数基准已更新: {', '.join(result.updated_symbols)}"]
    return []


def validate_incremental_quality() -> None:
    """校验增量库关键复权因子，不满足则停止生产候选流水线。"""
    import duckdb

    if INCREMENT_PATH.exists():
        with duckdb.connect(str(INCREMENT_PATH), read_only=True) as con:
            missing = con.execute(
                """
                SELECT d.trade_date, COUNT(*)
                FROM daily d
                LEFT JOIN adj_factor a
                  ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
                WHERE a.ts_code IS NULL
                GROUP BY d.trade_date
                ORDER BY d.trade_date DESC
                LIMIT 1
                """
            ).fetchone()
        if missing is not None:
            raise RuntimeError(f"A股增量复权因子缺失: {missing[0]} 缺失{missing[1]}条")
    if BENCHMARK_INCREMENT_PATH.exists():
        with duckdb.connect(str(BENCHMARK_INCREMENT_PATH), read_only=True) as con:
            missing = con.execute(
                """
                SELECT d.trade_date, COUNT(*)
                FROM fund_daily d
                LEFT JOIN fund_adj a
                  ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
                WHERE a.ts_code IS NULL
                GROUP BY d.trade_date
                ORDER BY d.trade_date DESC
                LIMIT 1
                """
            ).fetchone()
        if missing is not None:
            raise RuntimeError(f"ETF增量复权因子缺失: {missing[0]} 缺失{missing[1]}条")


def build_snapshot(update_warnings: list[str]) -> tuple[QualityPaperSnapshot, pd.DataFrame, object, pd.Series, pd.Series]:
    """复现冻结策略至最后完整交易日，并生成理论目标权重。"""
    con = open_live_market_connection(DB_PATH, INCREMENT_PATH)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        selections, holdings = build_top20_from_candidates(candidates)
        if not selections:
            raise RuntimeError("Quality策略没有可用选股结果")
        targets = {
            date: {symbol: 1.0 / len(symbols) for symbol in symbols}
            for date, symbols in selections.items()
            if symbols
        }
        calendar = load_calendar(con)
        bars = load_research_bars(con, sorted(holdings["symbol"].unique().tolist()))
        benchmark_curve, shanghai_curve, benchmark_label = load_dashboard_benchmarks(con)
        run = run_risk_layer_backtest(
            "Quality Cleanup + Volatility Overlay Paper",
            "GRID",
            targets,
            bars,
            calendar,
            benchmark_curve,
            ExecutionModel(slippage_bps=5.0),
            vol_window=VOL_WINDOW,
            vol_threshold=VOL_THRESHOLD,
            reduced_exposure=REDUCED_EXPOSURE,
        )
        latest_date = pd.Timestamp(run.result.daily_values.index.max())
        latest_exposure = float(run.exposure.loc[:latest_date].iloc[-1])
        returns = run.result.daily_values.pct_change().dropna().tail(VOL_WINDOW)
        volatility = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) >= VOL_WINDOW else 0.0
        selection_date = max(selections)
        symbols = selections[selection_date]
        warnings = list(update_warnings)
        warnings.append("Tushare账户无stock_st与suspend_d权限，ST/停牌状态沿用历史库")
        if benchmark_curve.empty:
            warnings.append(f"大盘基准不可用: {benchmark_label}")
        elif benchmark_curve.index.max() < latest_date:
            warnings.append(
                f"大盘基准{benchmark_label}仅到{benchmark_curve.index.max().strftime('%Y%m%d')}，"
                f"晚于该日的基准对比需等本地ETF/指数数据更新"
            )
        snapshot = QualityPaperSnapshot(
            trade_date=latest_date.strftime("%Y%m%d"),
            selection_date=selection_date,
            exposure=latest_exposure,
            volatility20=volatility,
            risk_state="REDUCED" if latest_exposure < 1 else "NORMAL",
            target_weights=build_target_weights(symbols, latest_exposure),
            warnings=warnings,
        )
        basic = con.execute("SELECT ts_code AS symbol, name FROM stock_basic").fetchdf()
        latest_holdings = pd.DataFrame({"symbol": symbols}).merge(basic, on="symbol", how="left")
        latest_holdings["target_weight"] = latest_holdings["symbol"].map(snapshot.target_weights)
        return snapshot, latest_holdings, run, benchmark_curve, shanghai_curve
    finally:
        con.close()


def update_monitoring_dashboard(run, benchmark_curve: pd.Series, shanghai_curve: pd.Series) -> None:
    """沉淀策略观测指标，并生成本地可视化报表。"""
    repository = MonitoringRepository(MONITORING_PATH)
    strategy_frame = build_strategy_monitor_frame(
        strategy_id="quality_overlay",
        strategy_name="Quality Cleanup + Volatility Overlay",
        daily_values=run.result.daily_values,
        benchmark_values=benchmark_curve,
        exposure=run.exposure,
        total_cost=run.result.total_cost,
        failed_order_count=len(run.result.failed_orders),
        turnover_notional=run.result.turnover_notional,
        benchmark_id="510300",
    )
    repository.upsert_strategy_daily(strategy_frame)
    market_frame = build_market_monitor_frame("510300", benchmark_curve)
    repository.upsert_market_daily(market_frame)
    shanghai_frame = build_market_monitor_frame("000001.SH", shanghai_curve)
    repository.upsert_market_daily(shanghai_frame)
    payload = build_dashboard_payload(
        repository,
        strategy_id="quality_overlay",
        benchmark_id="510300",
        benchmark_ids=["510300", "000001.SH"],
    )
    write_dashboard_files(payload, DASHBOARD_JSON_PATH, DASHBOARD_HTML_PATH)


def write_production_artifacts(
    snapshot: QualityPaperSnapshot,
    holdings: pd.DataFrame,
    run,
    benchmark_curve: pd.Series,
) -> Path:
    """写入 runs/YYYYMMDD 每日产物，并按月末生成月度复盘。"""
    store = QualityPaperStore(PAPER_PATH)
    previous = store.load_latest_before(snapshot.trade_date)
    run_dir = write_daily_artifacts(
        RUNS_ROOT,
        snapshot,
        holdings,
        run,
        benchmark_curve,
        previous_snapshot=previous,
    )
    repository = MonitoringRepository(MONITORING_PATH)
    system_repository = SystemRepository(RUNTIME_PATHS.system_state_path)
    register_quality_alpha_v1(system_repository)
    register_daily_artifacts(system_repository, snapshot.trade_date, run_dir)
    system_repository.record_strategy_run(
        "quality_overlay",
        snapshot.trade_date,
        "SUCCESS",
        run_dir,
        "daily pipeline completed",
    )
    if is_month_end_trade_date(snapshot.trade_date):
        month = snapshot.trade_date[:6]
        monthly_path = build_monthly_review(RUNS_ROOT, month, repository.load_strategy_history("quality_overlay"))
        system_repository.upsert_report(
            report_type="monthly_review",
            strategy_id="quality_overlay",
            trade_date=snapshot.trade_date,
            title=f"{month}月度复盘",
            file_path=monthly_path,
            tags=["monthly", "review"],
        )
    return run_dir


def register_daily_artifacts(repository: SystemRepository, trade_date: str, run_dir: Path) -> None:
    """把每日固定产物登记到系统状态库，供前端和报告中心统一读取。"""
    artifacts = [
        ("daily_report", "每日策略报告", "daily_report.md", ["daily", "report"]),
        ("rebalance_plan", "调仓建议", "rebalance_plan.csv", ["daily", "rebalance"]),
        ("portfolio_snapshot", "组合快照", "portfolio_snapshot.csv", ["daily", "portfolio"]),
        ("strategy_metrics", "策略指标", "strategy_metrics.json", ["daily", "metrics"]),
    ]
    for report_type, title, filename, tags in artifacts:
        repository.upsert_report(
            report_type=report_type,
            strategy_id="quality_overlay",
            trade_date=trade_date,
            title=title,
            file_path=run_dir / filename,
            tags=tags,
        )


def load_dashboard_benchmarks(con) -> tuple[pd.Series, pd.Series, str]:
    """读取510300与上证基准，优先拼接Tushare增量缓存。"""
    hs300_curve, label = load_hs300_benchmark(
        con,
        "20150101",
        str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
        str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
    )
    raw_increment = BenchmarkIncrementalStore(BENCHMARK_INCREMENT_PATH).load_raw_series()
    hs300_raw_base = _load_base_etf_raw("510300.SH")
    hs300_curve = _combine_raw_to_curve(hs300_raw_base, raw_increment.get("510300.SH", pd.Series(dtype=float)))
    if hs300_curve.empty:
        hs300_curve = _combine_raw_to_curve(pd.Series(dtype=float), raw_increment.get("510300.SH", pd.Series(dtype=float)))
    if hs300_curve.empty:
        hs300_curve = hs300_curve if not hs300_curve.empty else hs300_curve
    shanghai_curve = _combine_raw_to_curve(pd.Series(dtype=float), raw_increment.get("000001.SH", pd.Series(dtype=float)))
    return hs300_curve, shanghai_curve, label


def _load_base_etf_raw(symbol: str) -> pd.Series:
    """读取本地ETF基线的复权价格原序列。"""
    if not FUND_DAILY_PATH.exists():
        return pd.Series(dtype=float)
    import duckdb

    with duckdb.connect(str(FUND_DAILY_PATH), read_only=True) as con:
        frame = con.execute(
            """
            SELECT trade_date, close, adj_factor
            FROM etf_lof_reits_daily_adj
            WHERE ts_code = ?
            ORDER BY trade_date
            """,
            [symbol],
        ).fetchdf()
    if frame.empty:
        return pd.Series(dtype=float)
    values = frame["close"].astype(float) * frame["adj_factor"].astype(float)
    return pd.Series(values.values, index=pd.to_datetime(frame["trade_date"], format="%Y%m%d")).sort_index()


def _combine_raw_to_curve(base: pd.Series, increment: pd.Series) -> pd.Series:
    """拼接基线和增量原始价格，并归一化为净值。"""
    pieces = []
    if base is not None and not base.empty:
        pieces.append(base)
    if increment is not None and not increment.empty:
        inc = increment.copy()
        if pieces:
            inc = inc[inc.index > pieces[0].index.max()]
        pieces.append(inc)
    if not pieces:
        return pd.Series(dtype=float)
    raw = pd.concat(pieces).sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    return raw / float(raw.iloc[0])


def _latest_etf_base_date(symbol: str) -> str | None:
    if not FUND_DAILY_PATH.exists():
        return None
    import duckdb

    with duckdb.connect(str(FUND_DAILY_PATH), read_only=True) as con:
        value = con.execute(
            "SELECT MAX(trade_date) FROM etf_lof_reits_daily_adj WHERE ts_code = ?",
            [symbol],
        ).fetchone()[0]
    return str(value) if value else None


def _latest_index_base_date(symbol: str) -> str | None:
    """当前股票日线库没有指数时返回None，由Tushare指数缓存承担基线。"""
    import duckdb

    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            value = con.execute(
                "SELECT MAX(trade_date) FROM daily_adj_cache WHERE ts_code = ?",
                [symbol],
            ).fetchone()[0]
    except Exception:
        return None
    return str(value) if value else None


def _has_blocking_update_warning(warnings: list[str]) -> bool:
    """生产候选模式下，数据更新失败或无Token都阻止策略运行。"""
    return any("失败" in item or "未检测到TUSHARE_TOKEN" in item for item in warnings)


def render_report(snapshot: QualityPaperSnapshot, holdings: pd.DataFrame, updated_dates: list[str]) -> str:
    """生成盘后可直接阅读的Paper摘要。"""
    rows = "\n".join(
        f"| {index + 1} | {row.symbol} | {row['name'] or ''} | {row.target_weight:.2%} |"
        for index, row in holdings.iterrows()
    )
    warnings = "\n".join(f"- {item}" for item in snapshot.warnings) or "- 无"
    return f"""# Quality Overlay Paper Daily

- 数据日期：{snapshot.trade_date}
- Quality选股信号日：{snapshot.selection_date}
- 固定参数：20日组合波动率，阈值45%，触发后仓位30%
- 20日年化波动率：{snapshot.volatility20:.2%}
- 当前风险状态：{snapshot.risk_state}
- 股票总仓位：{snapshot.exposure:.2%}
- 现金目标：{1 - snapshot.exposure:.2%}
- 本次新增交易日：{', '.join(updated_dates) if updated_dates else '无'}

| 排名 | 股票 | 名称 | 目标权重 |
| --- | --- | --- | --- |
{rows}

## 数据告警

{warnings}
"""


def push_report(snapshot: QualityPaperSnapshot, bark_url: str) -> None:
    """仅推送风险状态和次日预案，不直接下单。"""
    title = "Quality Overlay Paper"
    body = (
        f"数据{snapshot.trade_date}，20日波动率{snapshot.volatility20:.2%}，"
        f"目标仓位{snapshot.exposure:.0%}，状态{snapshot.risk_state}。"
    )
    build_notifier("bark", bark_url).send(NotificationMessage(title, body))


def main() -> None:
    """更新数据、运行冻结策略、保存快照并可选推送。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-update", action="store_true", help="只使用当前完整缓存")
    parser.add_argument("--push", action="store_true", help="通过Bark推送摘要")
    parser.add_argument("--bark-url", default=os.getenv("BARK_PUSH_URL", ""))
    args = parser.parse_args()
    run_date = datetime.now().strftime("%Y%m%d")
    run_log_dir = RUNS_ROOT / run_date
    try:
        updated_dates: list[str] = []
        warnings: list[str] = []
        if not args.skip_update:
            updated_dates, warnings = update_incremental(run_date)
            warnings.extend(update_benchmark_incremental(run_date))
            if _has_blocking_update_warning(warnings):
                raise RuntimeError("; ".join(warnings))
        validate_incremental_quality()
        snapshot, holdings, run, benchmark_curve, shanghai_curve = build_snapshot(warnings)
        update_monitoring_dashboard(run, benchmark_curve, shanghai_curve)
        write_production_artifacts(snapshot, holdings, run, benchmark_curve)
        QualityPaperStore(PAPER_PATH).save(snapshot)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_report(snapshot, holdings, updated_dates), encoding="utf-8")
        print(REPORT_PATH.read_text(encoding="utf-8"))
        if args.push:
            if not args.bark_url:
                raise SystemExit("--push需要--bark-url或BARK_PUSH_URL")
            push_report(snapshot, args.bark_url)
    except Exception as exc:
        write_run_log(run_log_dir, "FAILED", str(exc))
        SystemRepository(RUNTIME_PATHS.system_state_path).record_strategy_run(
            "quality_overlay",
            run_date,
            "FAILED",
            run_log_dir,
            str(exc),
        )
        raise


if __name__ == "__main__":
    main()
