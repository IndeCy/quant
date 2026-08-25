"""真实大单与特大单净流入强度的数据可行性审计。"""

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
from data.order_flow import (
    ORDER_FLOW_ASOF_TABLE,
    OrderFlowClient,
    TushareOrderFlowClient,
    attach_order_flow_database,
    create_order_flow_signal_dates,
    materialize_large_order_flow_asof,
    update_order_flow_cache,
)
from data.signed_amount_pressure import (
    SIGNED_AMOUNT_PRESSURE_TABLE,
    materialize_signed_amount_pressure,
)
from examples.large_order_flow_feasibility_report import render_report
from examples.large_order_flow_feasibility_support import (
    load_source_diagnostics,
)
from factors.large_order_flow import score_large_order_flow_frame
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


EXPERIMENT_ID = "large_order_flow_data_feasibility_v1"
REPORT_PATH = Path("docs/research/large-order-flow-data-feasibility-v1.md")
FEASIBILITY_START = "20240101"
FETCH_START = "20231201"
LOCKED_START = "20250101"
LOOKBACK_TRADING_DAYS = 20
TOP_N = 40
MIN_CANDIDATES = 1_000
MIN_UNIQUE_VALUES = 800
MIN_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_PROXY_CORRELATION = 0.80
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="真实大单资金流数据可行性 V1",
    category="data_feasibility",
    hypothesis="真实订单规模分类能否形成独立、完整且可交易的月频候选池",
    definition={
        "factor": {
            "formula": (
                "sum((buy_lg+buy_elg)-(sell_lg+sell_elg),20d)"
                "/sum(all_classified_amount,20d)"
            ),
            "direction": "higher_is_better",
            "eligible": "positive_share_and_at_least_15_observations",
            "source_unit": "ten_thousand_cny",
        },
        "distinction": {
            "signed_amount_pressure": (
                "true_order_size_classification_not_price_direction_proxy"
            ),
            "maximum_allowed_median_rank_correlation": MAX_PROXY_CORRELATION,
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
            "qualified_month_share": MIN_MONTH_SHARE,
            "checked_and_successful_trade_day_share": 1.0,
            "source_row_limit_not_reached": 6_000,
            "net_identity_violation_share_max": 0.01,
            "turnover_ratio_p01_median_p99": [0.50, [0.80, 1.20], 1.50],
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "top40_tradable_share": MIN_TOP40_TRADABLE_SHARE,
            "visibility_duplicate_range_violations": 0,
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
    client_factory: Callable[[], OrderFlowClient] | None = None,
    request_interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """先登记确定性指纹，再同步和扫描真实订单流。"""
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
    client_factory: Callable[[], OrderFlowClient] | None,
    request_interval_seconds: float,
) -> dict[str, Any]:
    """缓存近年逐日数据并构造月末候选。"""
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
            raise ValueError("真实大单资金流研究没有月末信号日")
        trade_dates = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT trade_date
                FROM features
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [FETCH_START, signal_dates[-1]],
            ).fetchall()
        ]
    finally:
        connection.close()

    cache_path = paths.data_dir / "order_flow_increment.duckdb"
    if client_factory is None:
        token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
        client: OrderFlowClient = TushareOrderFlowClient(token)
    else:
        client = client_factory()
    sync = update_order_flow_cache(
        client,
        cache_path,
        trade_dates,
        request_interval_seconds=request_interval_seconds,
        progress_callback=_progress,
    )
    if not sync.success:
        preview = ",".join(sync.failed_dates[:5])
        raise RuntimeError(f"订单流逐日同步失败，待续跑日期: {preview}")

    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_signed_amount_pressure(connection, window=20)
        create_order_flow_signal_dates(connection, signal_dates)
        attach_order_flow_database(connection, cache_path)
        materialize_large_order_flow_asof(
            connection,
            lookback_trading_days=LOOKBACK_TRADING_DAYS,
        )
        source = load_investable_source(connection)
        diagnostics = load_source_diagnostics(connection, trade_dates)
    finally:
        connection.close()

    candidates = score_large_order_flow_frame(source)
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
    """应用标准股票池并连接旧量价代理供独立性审计。"""
    return connection.execute(
        f"""
        SELECT
            o.signal_date,
            o.symbol,
            o.latest_flow_date,
            o.observations,
            o.large_net_amount_wan,
            o.classified_amount_wan,
            o.large_order_net_share,
            o.total_net_share,
            o.source_net_turnover_share,
            f.amount20 * 1000.0 AS adv_rmb,
            f.vol60,
            f.ret20,
            f.ret120,
            s.signed_amount_pressure
        FROM {ORDER_FLOW_ASOF_TABLE} o
        JOIN features f
          ON o.signal_date = f.trade_date AND o.symbol = f.symbol
        JOIN {SIGNED_AMOUNT_PRESSURE_TABLE} s
          ON o.signal_date = s.trade_date AND o.symbol = s.symbol
        JOIN stock_basic sb ON o.symbol = sb.ts_code
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
        ORDER BY o.signal_date, o.symbol
        """
    ).fetchdf()


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月份并统计候选、流动性与机制相关性。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[candidates["signal_date"].astype(str).eq(signal_date)]
        factor = pd.to_numeric(group["large_order_net_share"], errors="coerce")
        selected = group.nlargest(TOP_N, "factor_score")
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(factor.notna().sum()),
                "unique_factor_values": int(factor.nunique()),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": float(adv.median()) if len(adv) else 0.0,
                "top40_tradable_share": float(adv.ge(5_000_000).mean())
                if len(adv)
                else 0.0,
                "spearman_amount20": _spearman(group, "factor_score", "adv_rmb"),
                "spearman_vol60": _spearman(group, "factor_score", "vol60"),
                "spearman_ret20": _spearman(group, "factor_score", "ret20"),
                "spearman_ret120": _spearman(group, "factor_score", "ret120"),
                "spearman_signed_amount": _spearman(
                    group,
                    "factor_score",
                    "signed_amount_pressure",
                ),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(candidates: pd.DataFrame) -> dict[str, float]:
    """记录最近非空月正向真实大单流分布。"""
    if candidates.empty:
        return {"p01": 0.0, "median": 0.0, "p99": 0.0}
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    values = pd.to_numeric(latest["large_order_net_share"], errors="coerce")
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
    """执行预注册覆盖、金额一致性与独立性门槛。"""
    if monthly.empty:
        raise ValueError("真实大单资金流覆盖审计没有预期月份")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    locked = monthly["signal_date"].astype(str).ge(LOCKED_START)
    full_share = float(qualified.mean())
    locked_share = float(qualified[locked].mean()) if locked.any() else 0.0
    proxy_correlation = float(monthly["spearman_signed_amount"].median())
    checks = {
        "qualified_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_qualified_month_share": locked_share >= MIN_MONTH_SHARE,
        "checked_trade_day_share": diagnostics["checked_trade_day_share"] == 1.0,
        "successful_trade_day_share": (
            diagnostics["successful_trade_day_share"] == 1.0
        ),
        "source_row_limit_not_reached": diagnostics["max_raw_rows"] < 6_000,
        "net_identity_consistent": (
            diagnostics["net_identity_violation_share"] <= 0.01
        ),
        "turnover_amount_consistent": (
            diagnostics["turnover_ratio_p01"] >= 0.50
            and 0.80 <= diagnostics["turnover_ratio_median"] <= 1.20
            and diagnostics["turnover_ratio_p99"] <= 1.50
        ),
        "distinct_from_signed_amount_proxy": (
            pd.notna(proxy_correlation)
            and abs(proxy_correlation) <= MAX_PROXY_CORRELATION
        ),
        "zero_duplicate_daily_rows": diagnostics["duplicate_daily_rows"] == 0,
        "zero_visibility_violations": diagnostics["visibility_violations"] == 0,
        "zero_factor_range_violations": (
            diagnostics["factor_range_violations"] == 0
        ),
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
        "latest_distribution": distribution,
        "median_correlations": {
            "amount20": float(monthly["spearman_amount20"].median()),
            "vol60": float(monthly["spearman_vol60"].median()),
            "ret20": float(monthly["spearman_ret20"].median()),
            "ret120": float(monthly["spearman_ret120"].median()),
            "signed_amount_pressure": proxy_correlation,
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
    """归档报告与逐月覆盖，门禁失败时禁止回测。"""
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
            "真实大单资金流覆盖和独立性稳定，可回补历史并固定回测"
            if result["passed"]
            else "真实大单资金流数据质量、覆盖或独立性未过门槛"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "真实大单流可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月覆盖明细"),
        ],
    )


def _spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    values = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(values[right], method="spearman"))


def _progress(current: int, total: int, trade_date: str) -> None:
    if current == 1 or current == total or current % 50 == 0:
        print(f"order_flow sync {current}/{total}: {trade_date}", flush=True)


def _data_version(paths: RuntimePaths, as_of_date: str) -> str:
    """绑定行情文件和远端订单流接口契约。"""
    parts = [f"tushare_moneyflow_daily:{FETCH_START}:{as_of_date}"]
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
