"""
Quality Factor Purity Study。

验证 Quality Cleanup 收益在行业、规模和部分行业剔除后是否仍存在。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import load_hs300_benchmark
from examples.quality_attribution_audit import (
    add_market_cap_bucket_by_universe,
    attach_valuation_exposure,
    create_annual_valuation_asof_table,
)
from examples.quality_cleanup_audit import (
    add_industry,
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    QUALITY_COLUMNS,
    START_DATE,
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
    run_monthly_backtest,
)


REPORT_PATH = Path("reports/quality_factor_purity_study.md")
RESOURCE_INDUSTRIES = {"有色金属", "煤炭", "石油石化", "基础化工"}


def score_within_group(frame: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """在指定组内对 Quality 因子做百分位排名并等权合成。"""
    scored = frame.dropna(subset=QUALITY_COLUMNS + [group_col]).copy()
    for column in QUALITY_COLUMNS:
        scored[f"{column}_rank"] = scored.groupby(group_col)[column].rank(pct=True, method="average")
    scored["neutral_score"] = scored[[f"{column}_rank" for column in QUALITY_COLUMNS]].mean(axis=1)
    return scored.sort_values(["neutral_score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_neutralized_selection(
    candidates: pd.DataFrame,
    group_col: str,
    top_n: int = 20,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按信号日做组内中性化排名并选 TopN。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_within_group(group, group_col)
        top = scored.head(top_n).copy()
        top["signal_date"] = str(signal_date)
        top["rank"] = range(1, len(top) + 1)
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    if not holdings:
        return selections, pd.DataFrame()
    return selections, pd.concat(holdings, ignore_index=True)


def run_variant_backtests(con, variants: dict[str, tuple[dict[str, list[str]], pd.DataFrame]]) -> pd.DataFrame:
    """统一执行多个纯度研究变体。"""
    symbols = sorted({symbol for selections, _ in variants.values() for symbols in selections.values() for symbol in symbols})
    bars = load_research_bars(con, symbols)
    calendar = load_calendar(con)
    execution_model = ExecutionModel(slippage_bps=5.0)
    results = {
        name: run_monthly_backtest(name, selections, bars, calendar, execution_model)
        for name, (selections, _) in variants.items()
    }
    benchmark_curve, _ = load_hs300_benchmark(
        con,
        START_DATE,
        str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
        str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
    )
    return build_metrics_table(results, benchmark_curve)


def format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化核心指标。"""
    formatted = frame.copy()
    for column in ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益"]:
        formatted[column] = formatted[column].map(format_percent)
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    return formatted


def render_report(metrics: pd.DataFrame, diagnostics: pd.DataFrame) -> str:
    """渲染纯度研究报告。"""
    positive_after_neutral = metrics.set_index("策略").loc[["行业中性化", "规模中性化"], "超额收益"].gt(0).all()
    answer = "仍存在" if positive_after_neutral else "明显减弱或不存在"
    return f"""# Quality Factor Purity Study

## 原策略收益 vs 中性化后收益

{markdown_table(format_metrics(metrics))}

## 变体说明

| 变体 | 含义 |
| --- | --- |
| Quality Cleanup 原策略 | 清理后候选池，原始 Quality 打分 Top20 |
| 行业中性化 | 每个行业内部对 ROE/ROA/ocf_to_or 做百分位排名，再全市场选 Top20 |
| 规模中性化 | 按当期候选池市值四分位分层，层内排名后选 Top20 |
| 剔除资源行业 | 剔除有色金属、煤炭、石油石化、基础化工后回测 |
| 剔除公用事业 | 剔除公用事业后回测 |

## 持仓诊断

{markdown_table(diagnostics)}

## 结论

若行业中性化和规模中性化后仍保留正收益和正超额，说明收益不完全依赖行业或规模；
若剔除资源/公用事业后仍保留收益，说明不是单一资源或公用事业暴露驱动。

当前结论：收益{answer}。
"""


def build_diagnostics(variants: dict[str, tuple[dict[str, list[str]], pd.DataFrame]]) -> pd.DataFrame:
    """汇总各变体持仓数量和覆盖情况。"""
    rows = []
    for name, (_, holdings) in variants.items():
        rows.append(
            {
                "变体": name,
                "持仓记录数": len(holdings),
                "去重股票数": holdings["symbol"].nunique() if not holdings.empty else 0,
                "未知行业占比": f"{(holdings['industry_level1'].eq('未知').mean() if 'industry_level1' in holdings else 0):.2%}",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    """运行纯度研究。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        create_annual_valuation_asof_table(con)
        base_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        base_candidates = add_industry(attach_valuation_exposure(con, base_candidates))
        base_candidates = add_market_cap_bucket_by_universe(base_candidates, base_candidates)

        variants = {
            "Quality Cleanup 原策略": build_top20_from_candidates(base_candidates),
            "行业中性化": build_neutralized_selection(base_candidates, "industry_level1"),
            "规模中性化": build_neutralized_selection(base_candidates, "market_cap_bucket"),
            "剔除资源行业": build_top20_from_candidates(
                base_candidates[~base_candidates["industry_level1"].isin(RESOURCE_INDUSTRIES)]
            ),
            "剔除公用事业": build_top20_from_candidates(
                base_candidates[~base_candidates["industry_level1"].eq("公用事业")]
            ),
        }
        for name, (selections, holdings) in list(variants.items()):
            variants[name] = (selections, add_industry(holdings) if "industry_level1" not in holdings else holdings)

        metrics = run_variant_backtests(con, variants)
        diagnostics = build_diagnostics(variants)
        REPORT_PATH.write_text(render_report(metrics, diagnostics), encoding="utf-8")
        print(metrics.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
