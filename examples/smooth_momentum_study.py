"""跳过近月的120日价格路径连续性动量固定研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.smooth_momentum import (
    SMOOTH_MOMENTUM_TABLE,
    materialize_smooth_momentum,
)
from examples.earnings_express_acceleration_study import (
    LOCKED_TEST_START,
    TRAIN_RANGE,
    VALIDATION_RANGE,
    build_annual_metrics,
    evaluate_gate,
    load_quality_correlation,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.smooth_momentum import score_smooth_momentum_frame
from portfolio.topn import build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "smooth_skip_month_momentum_120d_v1"
REPORT_PATH = Path("docs/research/smooth-skip-month-momentum-120d-v1.md")
FORMATION_WINDOW = 120
SKIP_WINDOW = 20
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="平滑中期动量 V1",
    category="factor_strategy",
    hypothesis="由多数小幅上涨日持续累积的中期动量，能否优于少数跳涨驱动的普通动量",
    definition={
        "factor": {
            "momentum": "log(qfq_close_t_minus_20/qfq_close_t_minus_120)",
            "continuity": "(positive_days-negative_days)/100",
            "formula": "momentum*continuity",
            "positive_momentum_gate": True,
            "direction": "higher_is_better",
            "formation_window": FORMATION_WINDOW,
            "skip_window": SKIP_WINDOW,
            "transform": "cross_sectional_percentile_rank",
        },
        "source": {
            "provider": "local_duckdb",
            "fields": ["close_qfq"],
            "future_data": False,
        },
        "universe": {
            "name_filter": "daily_st_plus_name_history_asof",
            "rules": "all_a_listed_3y_ex_st_delisted_suspended_bottom20_amount",
        },
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "quality_return_correlation_max": 0.75,
            "no_parameter_grid": True,
        },
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在读取全A行情前登记确定性指纹。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """构造平滑动量截面并执行固定口径 M0 回测。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_smooth_momentum(
            connection,
            formation_window=FORMATION_WINDOW,
            skip_window=SKIP_WINDOW,
        )
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = load_month_end_signal_dates(connection)
        candidates = load_candidates(connection, signal_dates)
        data_quality = validate_data_quality(candidates)
        if not data_quality["passed"]:
            raise ValueError(f"平滑动量数据质量未通过: {data_quality}")
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("平滑动量没有产生历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    run = run_risk_layer_backtest(
        STRATEGY_ID,
        "GRID",
        targets,
        bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )
    periods = {
        "train": TRAIN_RANGE,
        "validation": VALIDATION_RANGE,
        "locked_test": (LOCKED_TEST_START, latest_date),
        "full": ("20150101", latest_date),
    }
    metrics = build_period_metrics({STRATEGY_ID: run.result}, benchmark, periods)[
        STRATEGY_ID
    ]
    annual = build_annual_metrics(run, benchmark, latest_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, annual, quality_correlation)
    latest_holdings = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            annual,
            gate,
            quality_correlation,
            diagnostics,
            data_quality,
            candidate_counts,
            latest_date,
        ),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "data_quality": data_quality,
        "candidate_counts": candidate_counts,
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "momentum_skip_recent",
                "path_continuity",
                "smooth_momentum",
                "vol60",
            ]
        ].to_dict("records"),
        "report_path": str(report_path),
        "reused": False,
    }


def load_candidates(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """读取标准可交易股票池与同日平滑动量。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE smooth_signal_dates(signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO smooth_signal_dates VALUES (?)",
        [(str(item),) for item in signal_dates],
    )
    return connection.execute(
        f"""
        WITH name_history AS (
            SELECT ts_code, name, start_date, end_date FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date FROM stock_name_manual
        ),
        name_asof AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                h.name AS asof_name,
                ROW_NUMBER() OVER(
                    PARTITION BY f.trade_date, f.symbol
                    ORDER BY h.start_date DESC
                ) AS rn
            FROM features f
            JOIN name_history h ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (SELECT signal_date FROM smooth_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            s.momentum_skip_recent,
            s.path_continuity,
            s.smooth_momentum,
            f.ret20,
            f.ret120,
            f.vol60
        FROM features f
        JOIN {SMOOTH_MOMENTUM_TABLE} s
          ON f.trade_date = s.trade_date AND f.symbol = s.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM smooth_signal_dates)
          AND f.st_name IS NULL
          AND NOT REGEXP_MATCHES(COALESCE(na.asof_name, sb.name, ''), 'ST|退')
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def validate_data_quality(candidates: pd.DataFrame) -> dict[str, Any]:
    """检查跳月收益恒等式和路径连续性范围。"""
    if candidates.empty:
        return {"passed": False, "months": 0}
    expected = (1 + candidates["ret120"]) / (1 + candidates["ret20"]) - 1
    error = (candidates["momentum_skip_recent"] - expected).abs()
    invalid_continuity = ~candidates["path_continuity"].between(-1, 1)
    counts = candidates.groupby("signal_date")["symbol"].nunique()
    return {
        "passed": bool(
            float(error.max()) <= 1e-8
            and not invalid_continuity.any()
            and counts.min() >= TOP_N
        ),
        "max_momentum_identity_error": float(error.max()),
        "invalid_continuity_rows": int(invalid_continuity.sum()),
        "months": int(len(counts)),
        "minimum_monthly_candidates": int(counts.min()),
    }


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """按月生成平滑动量 Top40 等权目标。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_smooth_momentum_frame(group)
        scored["signal_date"] = str(signal_date)
        counts[str(signal_date)] = len(scored)
        if len(scored) >= TOP_N:
            frames.append(scored)
    if not frames:
        empty = candidates.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
        return {}, empty, {"min": 0.0, "median": 0.0, "latest": 0.0}
    scores = pd.concat(frames, ignore_index=True)
    mapping, holdings = build_topn_selections(scores, "factor_score", TOP_N)
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mapping.items()
    }
    count_series = pd.Series(counts, dtype=float)
    return targets, holdings, {
        "min": float(count_series.min()),
        "median": float(count_series.median()),
        "latest": float(count_series.iloc[-1]),
    }


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """衡量平滑动量与普通动量、低波的相关和持仓重合。"""
    momentum_correlations: list[float] = []
    vol_correlations: list[float] = []
    momentum_overlaps: list[float] = []
    low_vol_overlaps: list[float] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        valid = group.dropna(
            subset=["smooth_momentum", "momentum_skip_recent", "vol60"]
        )
        valid = valid[valid["momentum_skip_recent"].gt(0)]
        if len(valid) < TOP_N:
            continue
        momentum_correlations.append(
            float(valid["smooth_momentum"].rank().corr(valid["momentum_skip_recent"].rank()))
        )
        vol_correlations.append(
            float(valid["smooth_momentum"].rank().corr(valid["vol60"].rank()))
        )
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        momentum_top = set(
            valid.nlargest(TOP_N, "momentum_skip_recent")["symbol"].astype(str)
        )
        low_vol = set(valid.nsmallest(TOP_N, "vol60")["symbol"].astype(str))
        momentum_overlaps.append(len(selected & momentum_top) / TOP_N)
        low_vol_overlaps.append(len(selected & low_vol) / TOP_N)
    return {
        "median_spearman_with_skip_momentum": _median(momentum_correlations),
        "median_spearman_with_vol60": _median(vol_correlations),
        "median_top40_overlap_with_momentum": _median(momentum_overlaps),
        "median_top40_overlap_with_lowvol": _median(low_vol_overlaps),
    }

def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档报告和持仓，未过门槛时不注册生产策略。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if passed else "REJECTED",
        decision_reason=(
            "平滑动量通过固定样本外门槛，允许进入独立确认"
            if passed
            else "平滑动量未通过固定门槛，归档且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top40持仓"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    diagnostics: dict[str, float],
    data_quality: dict[str, Any],
    candidate_counts: dict[str, float],
    latest_date: str,
) -> str:
    """生成平滑动量固定研究报告。"""
    period_rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for period, item in metrics.items()
    )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in annual.items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# 平滑中期动量 V1

- 数据截止：{latest_date}。
- 固定因子：120日至20日前对数收益乘以该100日区间上涨日占优程度。
- 执行：正中期收益池、Top40月频等权、qfq、M0 T+1、5bps及固定风险层。
- 跳月收益恒等式最大误差：
  {data_quality['max_momentum_identity_error']:.3e}。
- 月度候选数：最少 {candidate_counts['min']:.0f}，中位数
  {candidate_counts['median']:.0f}，最新 {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与普通跳月动量Spearman中位数：
  {diagnostics['median_spearman_with_skip_momentum']:.3f}；Top40重合：
  {diagnostics['median_top40_overlap_with_momentum']:.1%}。
- 与60日波动率Spearman中位数：
  {diagnostics['median_spearman_with_vol60']:.3f}；低波Top40重合：
  {diagnostics['median_top40_overlap_with_lowvol']:.1%}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入独立确认，不直接注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""


def _median(values: list[float]) -> float:
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")


def _data_version(paths: RuntimePaths) -> str:
    """绑定股票行情基线与增量文件版本。"""
    parts = []
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
