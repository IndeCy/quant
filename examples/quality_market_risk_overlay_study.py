"""
Quality Cleanup 市场风险覆盖层研究。

不修改 ROE、ROA、OCF 因子、股票池和 Top20 等权组合，只改变总仓位。
"""

from __future__ import annotations

from pathlib import Path
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import load_hs300_benchmark
from examples.quality_cleanup_audit import (
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_portfolio_construction_study import run_weighted_monthly_backtest
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    attach_financial_dbs,
    create_signal_date_table,
)
from examples.strategy_comparison_research import (
    build_metrics_table,
    create_feature_table,
    format_percent,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
)


REPORT_PATH = Path("reports/quality_market_risk_overlay_study.md")
BENCHMARK_LOOKBACK_START = "20130101"


def build_market_exposure(
    benchmark_curve: pd.Series,
    short_window: int,
    long_window: int,
    weak_exposure: float,
) -> pd.Series:
    """根据基准均线关系生成目标总仓位。"""
    short_ma = benchmark_curve.rolling(short_window, min_periods=short_window).mean()
    long_ma = benchmark_curve.rolling(long_window, min_periods=long_window).mean()
    valid = short_ma.notna() & long_ma.notna()
    exposure = pd.Series(float("nan"), index=benchmark_curve.index, dtype="float64")
    exposure.loc[valid] = weak_exposure
    exposure.loc[valid & short_ma.gt(long_ma)] = 1.0
    return exposure


def build_overlay_targets(
    base_targets: dict[str, dict[str, float]],
    exposure: pd.Series,
    calendar: list[pd.Timestamp],
) -> dict[str, dict[str, float]]:
    """仅在月度调仓或风险仓位变化时生成目标权重。"""
    aligned = exposure.reindex(pd.DatetimeIndex(calendar)).ffill()
    targets: dict[str, dict[str, float]] = {}
    current_quality: dict[str, float] | None = None
    previous_exposure: float | None = None
    for date in calendar:
        date_key = date.strftime("%Y%m%d")
        monthly_rebalance = date_key in base_targets
        if monthly_rebalance:
            current_quality = base_targets[date_key]
        current_exposure = aligned.get(date)
        if current_quality is None or pd.isna(current_exposure):
            continue
        exposure_changed = previous_exposure is None or float(current_exposure) != previous_exposure
        if monthly_rebalance or exposure_changed:
            targets[date_key] = {
                symbol: weight * float(current_exposure) for symbol, weight in current_quality.items()
            }
        previous_exposure = float(current_exposure)
    return targets


def average_exposure(exposure: pd.Series, calendar: list[pd.Timestamp], start_date: str) -> float:
    """计算研究期平均目标仓位。"""
    aligned = exposure.reindex(pd.DatetimeIndex(calendar)).ffill()
    aligned = aligned.loc[pd.Timestamp(start_date) :].dropna()
    return float(aligned.mean()) if not aligned.empty else 0.0


def drawdown_attribution(strategy_values: pd.Series, benchmark_curve: pd.Series) -> dict[str, float | str]:
    """用回撤前 Beta 将最大回撤拆成市场与选股残差。"""
    running_max = strategy_values.expanding().max()
    drawdown = strategy_values / running_max - 1
    trough = drawdown.idxmin()
    peak = strategy_values.loc[:trough].idxmax()
    benchmark = benchmark_curve.reindex(strategy_values.index).ffill().dropna()
    benchmark_peak = float(benchmark.loc[:peak].iloc[-1])
    benchmark_trough = float(benchmark.loc[:trough].iloc[-1])
    benchmark_return = benchmark_trough / benchmark_peak - 1
    portfolio_return = float(strategy_values.loc[trough] / strategy_values.loc[peak] - 1)

    returns = pd.concat(
        [strategy_values.pct_change().rename("portfolio"), benchmark.pct_change().rename("benchmark")],
        axis=1,
    ).dropna()
    estimation = returns.loc[:peak].tail(120)
    variance = estimation["benchmark"].var()
    beta = float(estimation["portfolio"].cov(estimation["benchmark"]) / variance) if variance > 0 else 1.0
    portfolio_log = math.log1p(portfolio_return)
    market_log = beta * math.log1p(benchmark_return)
    selection_log = portfolio_log - market_log
    total_abs = abs(portfolio_log) if portfolio_log else 1.0
    return {
        "回撤开始": peak.strftime("%Y-%m-%d"),
        "回撤结束": trough.strftime("%Y-%m-%d"),
        "组合跌幅": portfolio_return,
        "HS300同期跌幅": benchmark_return,
        "回撤前Beta": beta,
        "直接市场跌幅占比": abs(benchmark_return) / abs(portfolio_return),
        "市场贡献比例": abs(market_log) / total_abs,
        "选股残差比例": abs(selection_log) / total_abs,
    }


def format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化统一输出指标。"""
    formatted = frame.copy()
    for column in ["年化收益", "最大回撤", "总收益", "基准收益", "超额收益", "持仓比例"]:
        formatted[column] = formatted[column].map(format_percent)
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    return formatted[["策略", "年化收益", "最大回撤", "夏普比率", "超额收益", "持仓比例"]]


def render_report(metrics: pd.DataFrame, attribution: dict[str, float | str]) -> str:
    """渲染市场风险覆盖层研究报告。"""
    attribution_frame = pd.DataFrame(
        [
            {"项目": "回撤开始日期", "结果": attribution["回撤开始"]},
            {"项目": "回撤结束日期", "结果": attribution["回撤结束"]},
            {"项目": "Quality Cleanup同期跌幅", "结果": f"{attribution['组合跌幅']:.2%}"},
            {"项目": "HS300同期跌幅", "结果": f"{attribution['HS300同期跌幅']:.2%}"},
            {"项目": "回撤前120日Beta", "结果": f"{attribution['回撤前Beta']:.2f}"},
            {"项目": "HS300跌幅/组合跌幅", "结果": f"{attribution['直接市场跌幅占比']:.2%}"},
            {"项目": "市场风险贡献", "结果": f"{attribution['市场贡献比例']:.2%}"},
            {"项目": "选股残差贡献", "结果": f"{attribution['选股残差比例']:.2%}"},
            {"项目": "MA60/MA120首次转弱", "结果": attribution["MA60/MA120首次转弱"]},
            {"项目": "MA120/MA250首次转弱", "结果": attribution["MA120/MA250首次转弱"]},
        ]
    )
    base = metrics[metrics["策略"].eq("Quality Cleanup 原策略")].iloc[0]
    overlays = metrics[~metrics["策略"].eq("Quality Cleanup 原策略")].copy()
    overlays["回撤改善"] = overlays["最大回撤"] - base["最大回撤"]
    best = overlays.sort_values(["回撤改善", "年化收益"], ascending=False).iloc[0]
    effective = bool(best["回撤改善"] >= 0.1)
    return f"""# Quality Market Risk Overlay Study

## 统一结果

{markdown_table(format_metrics(metrics))}

## 最大回撤归因

{markdown_table(attribution_frame)}

## 研究结论

1. 回撤来源：市场贡献约 `{attribution['市场贡献比例']:.2%}`，选股残差约 `{attribution['选股残差比例']:.2%}`。
2. Risk Overlay 是否有效：`{'有效' if effective else '效果有限'}`；最大回撤改善最多的是 `{best['策略']}`。
3. 是否值得进入 Quality V2：`{'值得' if effective else '暂不值得直接进入'}`。
4. 下一阶段最优研究方向：验证趋势信号切换成本、震荡期反复交易和不同市场阶段稳定性，不修改 Quality Alpha。

归因采用回撤前 120 个交易日 Beta 的对数收益分解，是风险解释而非精确因果归因。
"""


def main() -> None:
    """运行四组市场风险覆盖层实验。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        selections, holdings = build_top20_from_candidates(candidates)
        base_targets = {
            date: {symbol: 1.0 / len(symbols) for symbol in symbols}
            for date, symbols in selections.items()
            if symbols
        }
        calendar = load_calendar(con)
        benchmark, _ = load_hs300_benchmark(
            con,
            BENCHMARK_LOOKBACK_START,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        exposures = {
            "Market Trend Filter MA60>MA120": build_market_exposure(benchmark, 60, 120, 0.0),
            "Risk Scaling MA60>MA120": build_market_exposure(benchmark, 60, 120, 0.3),
            "Long Trend Filter MA120>MA250": build_market_exposure(benchmark, 120, 250, 0.0),
        }
        variant_targets = {"Quality Cleanup 原策略": base_targets}
        for name, exposure in exposures.items():
            variant_targets[name] = build_overlay_targets(base_targets, exposure, calendar)
        symbols = sorted(holdings["symbol"].unique().tolist())
        bars = load_research_bars(con, symbols)
        execution_model = ExecutionModel(slippage_bps=5.0)
        results = {
            name: run_weighted_monthly_backtest(name, targets, bars, calendar, execution_model)
            for name, targets in variant_targets.items()
        }
        metrics = build_metrics_table(results, benchmark)
        first_signal = min(base_targets)
        exposure_map = {"Quality Cleanup 原策略": 1.0}
        exposure_map.update(
            {name: average_exposure(exposure, calendar, first_signal) for name, exposure in exposures.items()}
        )
        metrics["持仓比例"] = metrics["策略"].map(exposure_map)
        attribution = drawdown_attribution(results["Quality Cleanup 原策略"].daily_values, benchmark)
        peak = pd.Timestamp(str(attribution["回撤开始"]))
        for name, key in [
            ("Market Trend Filter MA60>MA120", "MA60/MA120首次转弱"),
            ("Long Trend Filter MA120>MA250", "MA120/MA250首次转弱"),
        ]:
            weak = exposures[name].loc[peak:]
            weak = weak[weak.eq(0.0)]
            attribution[key] = weak.index[0].strftime("%Y-%m-%d") if not weak.empty else "未触发"
        REPORT_PATH.write_text(render_report(metrics, attribution), encoding="utf-8")
        print(metrics[["策略", "年化收益", "最大回撤", "夏普比率", "超额收益", "持仓比例"]].to_string(index=False))
        print(attribution)
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
