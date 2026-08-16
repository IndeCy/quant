"""北向个股持仓占比增加因子的月末数据可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any, Callable

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.hk_hold import (
    HK_HOLD_CHANGE_TABLE,
    HkHoldClient,
    HkHoldDuckDBStore,
    TushareHkHoldClient,
    attach_hk_hold_database,
    create_hk_hold_signal_dates,
    materialize_hk_hold_change_asof,
    update_hk_hold_month_ends,
)
from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from factors.hk_hold_change import score_hk_hold_change_frame
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


EXPERIMENT_ID = "hk_hold_change_data_feasibility_v1"
REPORT_PATH = Path("docs/research/hk-hold-change-data-feasibility-v1.md")
STUDY_START = "20170101"
LOCKED_START = "20240101"
TOP_N = 40
MIN_CANDIDATES = 250
MIN_UNIQUE_VALUES = 200
MIN_FULL_MONTH_SHARE = 0.85
MIN_LOCKED_MONTH_SHARE = 0.90
MIN_NONEMPTY_SNAPSHOT_SHARE = 0.85
MIN_SNAPSHOT_ROWS = 700
MIN_TOP40_MEDIAN_ADV_RMB = 10_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="北向持仓占比增加数据可行性 V1",
    category="data_feasibility",
    hypothesis="北向持仓占比月度增加能否形成稳定、可交易且点时正确的独立候选池",
    definition={
        "factor": {
            "formula": "current_holding_ratio-prior_holding_ratio",
            "direction": "higher_is_better",
            "eligible": "positive_change_only",
            "comparison": "same_symbol_in_adjacent_month_end_snapshots",
            "source_scope": "exchange_in_SH_SZ_northbound_a_shares_only",
        },
        "timing": {
            "signal": "a_share_month_end_close",
            "snapshot": "exact_signal_date_only",
            "execution": "future_fixed_backtest_t_plus_1",
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "full_qualified_month_share": MIN_FULL_MONTH_SHARE,
            "locked_qualified_month_share": MIN_LOCKED_MONTH_SHARE,
            "nonempty_snapshot_share": MIN_NONEMPTY_SNAPSHOT_SHARE,
            "minimum_nonempty_snapshot_rows": MIN_SNAPSHOT_ROWS,
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "top40_tradable_share": MIN_TOP40_TRADABLE_SHARE,
            "visibility_and_duplicate_violations": 0,
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
    client_factory: Callable[[], HkHoldClient] | None = None,
) -> dict[str, Any]:
    """先登记确定性指纹，再执行月末缓存和覆盖扫描。"""
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
        result = _calculate(paths, as_of_date, client_factory)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
    client_factory: Callable[[], HkHoldClient] | None,
) -> dict[str, Any]:
    """缓存预期月末快照，并应用标准股票池完成可行性门禁。"""
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
            if STUDY_START <= value <= latest_date
        ]
    finally:
        connection.close()
    if len(signal_dates) < 2:
        raise ValueError("北向持仓研究缺少至少两个连续月末信号日")

    cache_path = paths.data_dir / "hk_hold_increment.duckdb"
    store = HkHoldDuckDBStore(cache_path)
    if client_factory is None:
        token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
        client: HkHoldClient = TushareHkHoldClient(token)
    else:
        client = client_factory()
    sync = update_hk_hold_month_ends(client, store, signal_dates)

    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        create_hk_hold_signal_dates(connection, signal_dates)
        attach_hk_hold_database(connection, cache_path)
        materialize_hk_hold_change_asof(connection)
        source = load_investable_source(connection)
        diagnostics = load_source_diagnostics(connection, signal_dates)
    finally:
        connection.close()

    candidates = score_hk_hold_change_frame(source)
    monthly = build_monthly_coverage(candidates, signal_dates[1:])
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
    """使用统一前复权行情特征和点时名称过滤构建研究截面。"""
    return connection.execute(
        f"""
        SELECT
            h.signal_date,
            h.symbol,
            h.current_trade_date,
            h.prior_trade_date,
            h.period_gap_days,
            h.current_holding_ratio,
            h.prior_holding_ratio,
            h.holding_ratio_change,
            f.amount20 * 1000.0 AS adv_rmb,
            f.vol60,
            f.ret120
        FROM {HK_HOLD_CHANGE_TABLE} h
        JOIN features f
          ON h.signal_date = f.trade_date AND h.symbol = f.symbol
        JOIN stock_basic sb ON h.symbol = sb.ts_code
        WHERE h.current_trade_date = h.signal_date
          AND h.exchange IN ('SH', 'SZ')
          AND f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
          AND NOT REGEXP_MATCHES(COALESCE(sb.name, ''), 'ST|退')
        ORDER BY h.signal_date, h.symbol
        """
    ).fetchdf()


def load_source_diagnostics(
    connection: Any,
    signal_dates: list[str],
) -> dict[str, float]:
    """审计快照覆盖、越界、重复和连续月末间隔。"""
    source = connection.execute(
        f"""
        SELECT
            SUM(CASE WHEN current_trade_date > signal_date
                       OR prior_trade_date > signal_date THEN 1 ELSE 0 END),
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol),
            SUM(CASE WHEN current_holding_ratio NOT BETWEEN 0 AND 100
                       OR prior_holding_ratio NOT BETWEEN 0 AND 100
                     THEN 1 ELSE 0 END),
            SUM(CASE WHEN period_gap_days NOT BETWEEN 20 AND 45
                     THEN 1 ELSE 0 END)
        FROM {HK_HOLD_CHANGE_TABLE}
        """
    ).fetchone()
    placeholders = ",".join("?" for _ in signal_dates)
    snapshots = connection.execute(
        f"""
        WITH a_share_counts AS (
            SELECT trade_date, COUNT(*) AS row_count
            FROM hk_hold_db.hk_hold_snapshots
            WHERE exchange IN ('SH', 'SZ')
            GROUP BY trade_date
        )
        SELECT
            d.signal_date AS trade_date,
            l.trade_date IS NOT NULL AS checked,
            COALESCE(c.row_count, 0) AS row_count
        FROM hk_hold_signal_dates d
        LEFT JOIN hk_hold_db.hk_hold_sync_log l
          ON d.signal_date = l.trade_date
        LEFT JOIN a_share_counts c
          ON d.signal_date = c.trade_date
        WHERE d.signal_date IN ({placeholders})
        ORDER BY d.signal_date
        """,
        signal_dates,
    ).fetchdf()
    counts = pd.to_numeric(snapshots["row_count"], errors="coerce").fillna(0)
    nonempty = counts[counts.gt(0)]
    recent = snapshots["trade_date"].astype(str).ge("20240819")
    return {
        "visibility_violations": float(source[0] or 0),
        "duplicate_signal_symbol_rows": float(source[1] or 0),
        "ratio_range_violations": float(source[2] or 0),
        "gap_violations": float(source[3] or 0),
        "checked_snapshot_share": float(snapshots["checked"].astype(bool).mean()),
        "nonempty_snapshot_share": float(counts.gt(0).sum() / len(signal_dates)),
        "post_disclosure_change_nonempty_share": float(
            counts[recent].gt(0).mean() if recent.any() else 0.0
        ),
        "minimum_nonempty_snapshot_rows": float(
            nonempty.min() if not nonempty.empty else 0
        ),
        "latest_snapshot_rows": float(counts.iloc[-1] if not counts.empty else 0),
    }


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月份，统计候选可辨识性和 Top40 流动性。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[candidates["signal_date"].astype(str).eq(signal_date)]
        values = pd.to_numeric(group["holding_ratio_change"], errors="coerce")
        selected = group.nlargest(TOP_N, "factor_score")
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(values.notna().sum()),
                "unique_factor_values": int(values.nunique()),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": float(adv.median()) if len(adv) else 0.0,
                "top40_tradable_share": float(adv.ge(5_000_000).mean())
                if len(adv)
                else 0.0,
                "spearman_amount20": _spearman(group, "factor_score", "adv_rmb"),
                "spearman_vol60": _spearman(group, "factor_score", "vol60"),
                "spearman_ret120": _spearman(group, "factor_score", "ret120"),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(candidates: pd.DataFrame) -> dict[str, float]:
    """记录最近非空月的持仓占比增量分布。"""
    if candidates.empty:
        return {"p01": 0.0, "median": 0.0, "p99": 0.0}
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    values = pd.to_numeric(latest["holding_ratio_change"], errors="coerce")
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
    """按冻结门槛决定是否允许运行收益回测。"""
    if monthly.empty:
        raise ValueError("北向持仓覆盖审计没有预期月份")
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
    checks = {
        "full_qualified_month_share": full_share >= MIN_FULL_MONTH_SHARE,
        "locked_qualified_month_share": locked_share >= MIN_LOCKED_MONTH_SHARE,
        "nonempty_snapshot_share": (
            diagnostics["nonempty_snapshot_share"] >= MIN_NONEMPTY_SNAPSHOT_SHARE
        ),
        "minimum_nonempty_snapshot_rows": (
            diagnostics["minimum_nonempty_snapshot_rows"] >= MIN_SNAPSHOT_ROWS
        ),
        "zero_visibility_violations": diagnostics["visibility_violations"] == 0,
        "zero_duplicate_signal_symbol_rows": (
            diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
        "zero_ratio_range_violations": diagnostics["ratio_range_violations"] == 0,
        "zero_gap_violations": diagnostics["gap_violations"] == 0,
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
            "ret120": float(monthly["spearman_ret120"].median()),
        },
        "diagnostics": diagnostics,
        "sync": sync,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档覆盖明细与结论，不通过时不触发回测。"""
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
            "北向持仓月末覆盖稳定，可进入一次固定参数回测"
            if result["passed"]
            else "北向持仓覆盖或候选可交易性未过冻结门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "北向持仓可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成非收益导向的数据门禁报告。"""
    diagnostics = result["diagnostics"]
    distribution = result["latest_distribution"]
    correlations = result["median_correlations"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 北向持仓占比增加数据可行性 V1

- 数据截止：{result['latest_date']}，预期月末 {result['signal_months']} 个。
- 合格月份（全样本/2024年至今）：{result['qualified_month_share']:.2%} /
  {result['locked_qualified_month_share']:.2%}。
- 正向候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 因子唯一值中位数：{result['unique_values_median']:.0f}。
- A股北向非空快照覆盖/最少行数/最新行数：
  {diagnostics['nonempty_snapshot_share']:.2%} /
  {diagnostics['minimum_nonempty_snapshot_rows']:.0f} /
  {diagnostics['latest_snapshot_rows']:.0f}。
- 2024-08-19 披露变化后，A股北向非空月占比：
  {diagnostics['post_disclosure_change_nonempty_share']:.2%}。
- 最新正向变化 P1/中位/P99：{distribution['p01']:.4f} /
  {distribution['median']:.4f} / {distribution['p99']:.4f} 个百分点。
- 因子与成交额/波动率/120日收益的月度 Spearman 中位：
  {correlations['amount20']:.3f} / {correlations['vol60']:.3f} /
  {correlations['ret120']:.3f}。
- 公告越界/重复/比例越界/月间隔异常：
  {diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_signal_symbol_rows']:.0f} /
  {diagnostics['ratio_range_violations']:.0f} /
  {diagnostics['gap_violations']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段不计算收益，也不注册生产策略。
"""


def _spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    """计算横截面秩相关，样本不足时返回空值。"""
    values = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    return float(values[left].corr(values[right], method="spearman")) if len(values) > 2 else float("nan")


def _data_version(paths: RuntimePaths, as_of_date: str) -> str:
    """指纹绑定行情文件和远端接口契约，不依赖运行中会变化的缓存。"""
    parts = [f"tushare_hk_hold_month_end:{STUDY_START}:{as_of_date}"]
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
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
