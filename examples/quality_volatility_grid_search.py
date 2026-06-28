"""
Quality 波动率目标风险层网格研究。

固定 Quality Cleanup Alpha 与 Top20 月频等权，仅搜索风险层参数。
"""

from __future__ import annotations

from itertools import product
from pathlib import Path
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
from examples.quality_risk_layer_research import run_risk_layer_backtest
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


REPORT_PATH = Path("reports/quality_volatility_grid_search.md")
CSV_PATH = Path("reports/quality_volatility_grid_search.csv")
BENCHMARK_LOOKBACK_START = "20130101"
WINDOWS = [20, 40, 60, 90]
THRESHOLDS = [0.35, 0.40, 0.45, 0.50]
REDUCED_EXPOSURES = [0.50, 0.70, 0.30]


def add_calmar(metrics: pd.DataFrame) -> pd.DataFrame:
    """计算 Calmar 比率。"""
    result = metrics.copy()
    result["Calmar"] = result["年化收益"] / result["最大回撤"].abs().replace(0, pd.NA)
    return result


def format_grid(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化网格输出。"""
    formatted = frame.copy()
    for column in ["阈值", "低波动仓位", "年化收益", "最大回撤", "超额收益", "平均仓位"]:
        formatted[column] = formatted[column].map(format_percent)
    for column in ["夏普比率", "Calmar"]:
        formatted[column] = formatted[column].map(lambda value: f"{value:.3f}")
    return formatted[
        ["窗口", "阈值", "低波动仓位", "年化收益", "最大回撤", "夏普比率", "Calmar", "超额收益", "平均仓位"]
    ]


def render_report(grid: pd.DataFrame, baseline: pd.DataFrame) -> str:
    """渲染网格研究报告。"""
    sharpe_best = grid.sort_values(["夏普比率", "Calmar"], ascending=False).head(1)
    calmar_best = grid.sort_values(["Calmar", "夏普比率"], ascending=False).head(1)
    top_sharpe = grid.sort_values(["夏普比率", "Calmar"], ascending=False).head(10)
    top_calmar = grid.sort_values(["Calmar", "夏普比率"], ascending=False).head(10)
    baseline_display = baseline.copy()
    for column in ["年化收益", "最大回撤", "超额收益", "平均仓位"]:
        baseline_display[column] = baseline_display[column].map(format_percent)
    baseline_display["夏普比率"] = baseline_display["夏普比率"].map(lambda value: f"{value:.3f}")
    baseline_display["Calmar"] = baseline_display["Calmar"].map(lambda value: f"{value:.3f}")
    return f"""# Quality Volatility Grid Search

## 原策略对照

{markdown_table(baseline_display[["策略", "年化收益", "最大回撤", "夏普比率", "Calmar", "超额收益", "平均仓位"]])}

## 夏普最高组合

{markdown_table(format_grid(sharpe_best))}

## Calmar最高组合

{markdown_table(format_grid(calmar_best))}

## 夏普 Top10

{markdown_table(format_grid(top_sharpe))}

## Calmar Top10

{markdown_table(format_grid(top_calmar))}

## 全部48组

{markdown_table(format_grid(grid.sort_values(["窗口", "阈值", "低波动仓位"]))) }

## 说明

- 单阈值两档仓位：组合过去 N 日年化波动率高于阈值时降至指定仓位，否则100%。
- 所有信号在当日收盘生成，下一交易日执行。
- 这是样本内网格研究，最优参数需要做分年度和样本外稳定性验证后才能进入 Quality V2。
"""


def main() -> None:
    """运行全部48组风险层网格。"""
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
        bars = load_research_bars(con, sorted(holdings["symbol"].unique().tolist()))
        execution_model = ExecutionModel(slippage_bps=5.0)

        runs = {}
        parameter_rows = []
        combinations = list(product(WINDOWS, THRESHOLDS, REDUCED_EXPOSURES))
        for index, (window, threshold, reduced) in enumerate(combinations, start=1):
            name = f"W{window}_T{int(threshold * 100)}_E{int(reduced * 100)}"
            run = run_risk_layer_backtest(
                name,
                "GRID",
                base_targets,
                bars,
                calendar,
                benchmark,
                execution_model,
                vol_window=window,
                vol_threshold=threshold,
                reduced_exposure=reduced,
            )
            runs[name] = run
            parameter_rows.append(
                {
                    "策略": name,
                    "窗口": window,
                    "阈值": threshold,
                    "低波动仓位": reduced,
                    "平均仓位": float(run.exposure.mean()),
                }
            )
            print(f"[{index:02d}/{len(combinations)}] {name}")

        baseline_run = run_risk_layer_backtest(
            "Quality Cleanup 原策略",
            "BASE",
            base_targets,
            bars,
            calendar,
            benchmark,
            execution_model,
        )
        result_map = {name: run.result for name, run in runs.items()}
        grid = build_metrics_table(result_map, benchmark).merge(pd.DataFrame(parameter_rows), on="策略")
        grid = add_calmar(grid)
        baseline = build_metrics_table({"Quality Cleanup 原策略": baseline_run.result}, benchmark)
        baseline["平均仓位"] = float(baseline_run.exposure.mean())
        baseline = add_calmar(baseline)
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        grid.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        REPORT_PATH.write_text(render_report(grid, baseline), encoding="utf-8")
        print("夏普最高:")
        print(grid.sort_values(["夏普比率", "Calmar"], ascending=False).head(1).to_string(index=False))
        print("Calmar最高:")
        print(grid.sort_values(["Calmar", "夏普比率"], ascending=False).head(1).to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
        print(f"完整网格已写入: {CSV_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
