"""机构席位近20日净买入强度的数据可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any, Callable

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from data.top_inst import (
    TOP_INST_ASOF_TABLE,
    TopInstClient,
    TushareTopInstClient,
    attach_top_inst_database,
    create_top_inst_signal_dates,
    materialize_top_inst_flow_asof,
    update_top_inst_cache,
)
from factors.top_inst_flow import score_top_inst_flow_frame
from examples.top_inst_flow_feasibility_report import render_report
from runtime.config import get_config_value
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "top_inst_flow_data_feasibility_v1"
REPORT_PATH = Path("docs/research/top-inst-flow-data-feasibility-v1.md")
FEASIBILITY_START = "20240101"
FETCH_LOOKBACK_START = "20231201"
LOCKED_START = "20250101"
LOOKBACK_TRADING_DAYS = 20
TOP_N = 20
MIN_CANDIDATES = 100
MIN_UNIQUE_VALUES = 80
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP20_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP20_TRADABLE_SHARE = 0.95
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="机构席位净买入强度数据可行性 V1",
    category="data_feasibility",
    hypothesis="龙虎榜机构席位净买入是否能形成稳定、点时正确且可交易的月频候选池",
    definition={
        "factor": {
            "formula": "deduplicated_20d_net_buy/amount20_rmb",
            "direction": "higher_is_better",
            "eligible": "positive_net_buy_only",
            "deduplication": (
                "trade_date_ts_code_exalter_buy_sell_net_buy_ignore_side_reason"
            ),
        },
        "window": {
            "length": LOOKBACK_TRADING_DAYS,
            "calendar": "real_a_share_trading_days",
            "signal": "month_end_close",
            "future_execution": "t_plus_1",
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio_candidate": {"top_n": TOP_N, "weight": "equal"},
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_QUALIFIED_MONTH_SHARE,
            "checked_trade_day_share": 1.0,
            "source_row_limit_not_reached": 10_000,
            "top20_median_adv_rmb": MIN_TOP20_MEDIAN_ADV_RMB,
            "top20_tradable_share": MIN_TOP20_TRADABLE_SHARE,
            "visibility_duplicate_identity_violations": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client_factory: Callable[[], TopInstClient] | None = None,
    request_interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """先登记研究指纹，再执行逐日缓存和覆盖审计。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths, as_of_date),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(
            paths,
            as_of_date,
            client_factory,
            request_interval_seconds,
        )
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
    client_factory: Callable[[], TopInstClient] | None,
    request_interval_seconds: float,
) -> dict[str, Any]:
    """同步近年机构席位明细并构造月末可交易截面。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if FEASIBILITY_START <= value <= latest_date
        ]
        if not signal_dates:
            raise ValueError("机构席位研究没有可用月末信号日")
        trade_dates = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT trade_date
                FROM features
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [FETCH_LOOKBACK_START, signal_dates[-1]],
            ).fetchall()
        ]
    finally:
        connection.close()

    cache_path = paths.data_dir / "top_inst_increment.duckdb"
    if client_factory is None:
        token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
        client: TopInstClient = TushareTopInstClient(token)
    else:
        client = client_factory()
    sync = update_top_inst_cache(
        client,
        cache_path,
        trade_dates,
        request_interval_seconds=request_interval_seconds,
        progress_callback=_progress,
    )
    if not sync.success:
        preview = ",".join(sync.failed_dates[:5])
        raise RuntimeError(f"机构席位逐日同步失败，待续跑日期: {preview}")

    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        create_top_inst_signal_dates(connection, signal_dates)
        attach_top_inst_database(connection, cache_path)
        materialize_top_inst_flow_asof(
            connection,
            lookback_trading_days=LOOKBACK_TRADING_DAYS,
        )
        source = load_investable_source(connection)
        diagnostics = load_source_diagnostics(connection, trade_dates)
    finally:
        connection.close()

    candidates = score_top_inst_flow_frame(source)
    monthly = build_monthly_coverage(candidates, signal_dates)
    distribution = build_latest_distribution(candidates)
    result = evaluate_feasibility(
        monthly,
        distribution,
        diagnostics,
        latest_date,
        sync.__dict__,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_investable_source(connection: Any) -> pd.DataFrame:
    """通过统一行情和标准股票池补充成交额、波动率与动量诊断。"""
    return connection.execute(
        f"""
        SELECT
            t.signal_date,
            t.symbol,
            t.latest_event_date,
            t.unique_seat_events,
            t.event_days,
            t.source_rows,
            t.total_buy,
            t.total_sell,
            t.total_net_buy,
            f.amount20 * 1000.0 AS adv_rmb,
            f.vol60,
            f.ret120
        FROM {TOP_INST_ASOF_TABLE} t
        JOIN features f
          ON t.signal_date = f.trade_date AND t.symbol = f.symbol
        JOIN stock_basic sb ON t.symbol = sb.ts_code
        WHERE f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
          AND NOT REGEXP_MATCHES(COALESCE(sb.name, ''), 'ST|退')
        ORDER BY t.signal_date, t.symbol
        """
    ).fetchdf()


def load_source_diagnostics(
    connection: Any,
    expected_trade_dates: list[str],
) -> dict[str, float]:
    """审计逐日完整性、源上限、去重、金额恒等式和点时越界。"""
    placeholders = ",".join("?" for _ in expected_trade_dates)
    sync = connection.execute(
        f"""
        SELECT trade_date, status, raw_row_count, normalized_row_count
        FROM top_inst_db.top_inst_sync_log
        WHERE trade_date IN ({placeholders})
        ORDER BY trade_date
        """,
        expected_trade_dates,
    ).fetchdf()
    source = connection.execute(
        """
        SELECT
            COUNT(*) - COUNT(DISTINCT event_key),
            SUM(CASE WHEN ABS(net_buy - (buy - sell)) > 0.05
                     THEN 1 ELSE 0 END),
            SUM(source_row_count),
            COUNT(*)
        FROM top_inst_db.top_inst_events
        """
    ).fetchone()
    visibility = connection.execute(
        f"""
        SELECT SUM(CASE WHEN latest_event_date > signal_date THEN 1 ELSE 0 END)
        FROM {TOP_INST_ASOF_TABLE}
        """
    ).fetchone()[0]
    raw = pd.to_numeric(sync["raw_row_count"], errors="coerce").fillna(0)
    normalized = pd.to_numeric(
        sync["normalized_row_count"],
        errors="coerce",
    ).fillna(0)
    return {
        "checked_trade_day_share": float(
            sync["trade_date"].nunique() / len(expected_trade_dates)
        ),
        "successful_trade_day_share": float(
            sync["status"].eq("SUCCESS").sum() / len(expected_trade_dates)
        ),
        "empty_trade_day_share": float(raw.eq(0).sum() / len(expected_trade_dates)),
        "max_raw_rows": float(raw.max() if not raw.empty else 0),
        "raw_rows": float(raw.sum()),
        "normalized_rows": float(normalized.sum()),
        "deduplicated_row_share": float(
            1.0 - normalized.sum() / raw.sum() if raw.sum() else 0.0
        ),
        "duplicate_event_keys": float(source[0] or 0),
        "net_buy_identity_violations": float(source[1] or 0),
        "source_rows_represented": float(source[2] or 0),
        "stored_unique_events": float(source[3] or 0),
        "visibility_violations": float(visibility or 0),
    }


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月份并统计候选广度、流动性和已有风格相关。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[candidates["signal_date"].astype(str).eq(signal_date)]
        factor = pd.to_numeric(group["net_buy_to_adv"], errors="coerce")
        selected = group.nlargest(TOP_N, "factor_score")
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(factor.notna().sum()),
                "unique_factor_values": int(factor.nunique()),
                "top20_count": int(len(selected)),
                "top20_median_adv_rmb": float(adv.median()) if len(adv) else 0.0,
                "top20_tradable_share": float(adv.ge(5_000_000).mean())
                if len(adv)
                else 0.0,
                "top20_median_event_days": float(
                    pd.to_numeric(
                        selected["event_days"],
                        errors="coerce",
                    ).median()
                )
                if len(selected)
                else 0.0,
                "spearman_amount20": _spearman(group, "factor_score", "adv_rmb"),
                "spearman_vol60": _spearman(group, "factor_score", "vol60"),
                "spearman_ret120": _spearman(group, "factor_score", "ret120"),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(candidates: pd.DataFrame) -> dict[str, float]:
    """记录最近非空月净买入强度分布。"""
    if candidates.empty:
        return {"p01": 0.0, "median": 0.0, "p99": 0.0}
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    values = pd.to_numeric(latest["net_buy_to_adv"], errors="coerce")
    return {
        "p01": float(values.quantile(0.01)),
        "median": float(values.median()),
        "p99": float(values.quantile(0.99)),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
    sync: dict[str, Any],
) -> dict[str, Any]:
    """按预注册门槛决定是否允许历史回补和收益回测。"""
    if monthly.empty:
        raise ValueError("机构席位覆盖审计没有预期月份")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top20_count"].eq(TOP_N)
        & monthly["top20_median_adv_rmb"].ge(MIN_TOP20_MEDIAN_ADV_RMB)
        & monthly["top20_tradable_share"].ge(MIN_TOP20_TRADABLE_SHARE)
    )
    locked = monthly["signal_date"].astype(str).ge(LOCKED_START)
    full_share = float(qualified.mean())
    locked_share = float(qualified[locked].mean()) if locked.any() else 0.0
    checks = {
        "qualified_month_share": full_share >= MIN_QUALIFIED_MONTH_SHARE,
        "locked_qualified_month_share": (
            locked_share >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "checked_trade_day_share": diagnostics["checked_trade_day_share"] == 1.0,
        "successful_trade_day_share": (
            diagnostics["successful_trade_day_share"] == 1.0
        ),
        "source_row_limit_not_reached": diagnostics["max_raw_rows"] < 10_000,
        "zero_duplicate_event_keys": diagnostics["duplicate_event_keys"] == 0,
        "zero_net_buy_identity_violations": (
            diagnostics["net_buy_identity_violations"] == 0
        ),
        "zero_visibility_violations": diagnostics["visibility_violations"] == 0,
    }
    passed = all(checks.values())
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "qualified_month_share": full_share,
        "locked_qualified_month_share": locked_share,
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "unique_values_median": float(monthly["unique_factor_values"].median()),
        "top20_median_event_days": float(
            monthly["top20_median_event_days"].median()
        ),
        "latest_distribution": distribution,
        "median_correlations": {
            "amount20": float(monthly["spearman_amount20"].median()),
            "vol60": float(monthly["spearman_vol60"].median()),
            "ret120": float(monthly["spearman_ret120"].median()),
        },
        "diagnostics": diagnostics,
        "sync": sync,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FULL_HISTORY_AND_FIXED_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档可行性结论和逐月覆盖明细。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if result["passed"] else "REJECTED",
        decision_reason=(
            "机构席位候选覆盖稳定，可回补完整历史并执行一次固定回测"
            if result["passed"]
            else "机构席位候选覆盖或数据完整性未过门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "机构席位可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月覆盖明细"),
        ],
    )


def _spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    values = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(values[right], method="spearman"))


def _progress(current: int, total: int, trade_date: str) -> None:
    """每50个交易日输出一次进度，便于长任务判断是否存活。"""
    if current == 1 or current == total or current % 50 == 0:
        print(f"top_inst sync {current}/{total}: {trade_date}", flush=True)


def _data_version(paths: RuntimePaths, as_of_date: str) -> str:
    """绑定行情文件和远端逐日接口契约，缓存增长不改变预注册指纹。"""
    parts = [f"tushare_top_inst_daily:{FETCH_LOOKBACK_START}:{as_of_date}"]
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--request-interval", type=float, default=0.0)
    args = parser.parse_args()
    print(
        run_study(
            get_runtime_paths(),
            args.as_of_date,
            force=args.force,
            request_interval_seconds=args.request_interval,
        )
    )


if __name__ == "__main__":
    main()
