"""
Quality Alpha Attribution（Quality Alpha V2）。

只解释 Quality Alpha V1，不新增因子、不改参数、不优化收益。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.live_market_view import open_live_market_connection
from examples.quality_attribution_audit import attach_valuation_exposure, bucket_market_cap, create_annual_valuation_asof_table
from examples.quality_cleanup_audit import (
    add_industry,
    apply_quality_cleanup_filters,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_risk_layer_research import run_risk_layer_backtest
from examples.quality_strategy_v1 import DB_PATH, QUALITY_COLUMNS, attach_financial_dbs, create_signal_date_table
from examples.run_quality_overlay_paper import INCREMENT_PATH, load_dashboard_benchmarks
from examples.strategy_comparison_research import create_feature_table, load_calendar, load_research_bars, load_signal_dates, markdown_table
from examples.quality_strategy_v1 import winsorize_series, zscore_series


REPORT_PATH = Path("reports/quality_alpha_attribution_v2.md")
VOL_WINDOW = 20
VOL_THRESHOLD = 0.45
REDUCED_EXPOSURE = 0.30

FACTOR_VARIANTS = {
    "Quality V1": ["roe", "roa", "ocf_to_or"],
    "ROE Only": ["roe"],
    "ROA Only": ["roa"],
    "OCF_TO_OR Only": ["ocf_to_or"],
    "ROE + ROA": ["roe", "roa"],
    "ROE + OCF_TO_OR": ["roe", "ocf_to_or"],
    "ROA + OCF_TO_OR": ["roa", "ocf_to_or"],
}


def score_factor_frame(frame: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """按指定 Quality 子集做同口径 winsorize + zscore + 等权打分。"""
    scored = frame.dropna(subset=factors).copy()
    for column in factors:
        scored[f"{column}_z"] = zscore_series(winsorize_series(scored[column]))
    scored["factor_score"] = scored[[f"{column}_z" for column in factors]].mean(axis=1)
    return scored.sort_values(["factor_score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_selections(candidates: pd.DataFrame, factors: list[str]) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按指定因子组合生成 Top20 月频持仓。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        top = score_factor_frame(group, factors).head(20).copy()
        top["signal_date"] = str(signal_date)
        top["rank"] = range(1, len(top) + 1)
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    return selections, pd.concat(holdings, ignore_index=True)


def calculate_metrics(values: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    """计算归因研究统一绩效指标。"""
    curve = values.dropna().astype(float).sort_index()
    returns = curve.pct_change().dropna()
    years = max(len(curve) / 252, 1)
    total_return = float(curve.iloc[-1] / curve.iloc[0] - 1)
    annual_return = (1 + total_return) ** (1 / years) - 1
    drawdown = curve / curve.cummax() - 1
    max_drawdown = float(drawdown.min())
    sharpe = float((returns.mean() / returns.std(ddof=1)) * (252**0.5)) if returns.std(ddof=1) else 0.0
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    aligned = benchmark.reindex(curve.index).ffill().dropna()
    benchmark_return = float(aligned.iloc[-1] / aligned.iloc[0] - 1) if not aligned.empty else 0.0
    return {
        "年化收益": annual_return,
        "最大回撤": max_drawdown,
        "夏普": sharpe,
        "Calmar": calmar,
        "总收益": total_return,
        "基准收益": benchmark_return,
        "超额收益": total_return - benchmark_return,
    }


def build_factor_correlation(frame: pd.DataFrame, factors: list[str]) -> dict[str, pd.DataFrame]:
    """输出 Pearson 与 Spearman 相关矩阵。"""
    numeric = frame[factors].apply(pd.to_numeric, errors="coerce").dropna()
    return {"pearson": numeric.corr(method="pearson"), "spearman": numeric.corr(method="spearman")}


def average_holding_overlap(left: dict[str, list[str]], right: dict[str, list[str]]) -> float:
    """按调仓日计算平均 Jaccard 持仓重叠率。"""
    scores = []
    for date in sorted(set(left) & set(right)):
        a, b = set(left[date]), set(right[date])
        if a or b:
            scores.append(len(a & b) / len(a | b))
    return float(pd.Series(scores).mean()) if scores else 0.0


def average_industry_overlap(left: pd.DataFrame, right: pd.DataFrame) -> float:
    """按调仓日计算行业集合重叠率。"""
    scores = []
    for date in sorted(set(left["signal_date"]) & set(right["signal_date"])):
        a = set(left[left["signal_date"].eq(date)]["industry_level1"])
        b = set(right[right["signal_date"].eq(date)]["industry_level1"])
        if a or b:
            scores.append(len(a & b) / len(a | b))
    return float(pd.Series(scores).mean()) if scores else 0.0


def build_marginal_contribution(metrics: pd.DataFrame, removed_map: dict[str, str]) -> pd.DataFrame:
    """比较删除某因子后相对 Quality V1 的多指标退化。"""
    base = metrics[metrics["策略"].eq("Quality V1")].iloc[0]
    rows = []
    for label, degraded_name in removed_map.items():
        degraded = metrics[metrics["策略"].eq(degraded_name)].iloc[0]
        rows.append(
            {
                "删除项": label,
                "退化策略": degraded_name,
                "Sharpe变化": float(degraded["夏普"] - base["夏普"]),
                "Calmar变化": float(degraded["Calmar"] - base["Calmar"]),
                "最大回撤变化": float(degraded["最大回撤"] - base["最大回撤"]),
                "超额收益变化": float(degraded["超额收益"] - base["超额收益"]),
            }
        )
    return pd.DataFrame(rows)


def annual_return_drawdown(values: pd.Series) -> pd.DataFrame:
    """逐年收益与年内最大回撤。"""
    rows = []
    curve = values.sort_index()
    for year, group in curve.groupby(curve.index.year):
        year_curve = group.astype(float)
        ret = float(year_curve.iloc[-1] / year_curve.iloc[0] - 1)
        dd = float((year_curve / year_curve.cummax() - 1).min())
        rows.append({"年份": int(year), "收益": ret, "最大回撤": dd})
    return pd.DataFrame(rows)


def summarize_industry(holdings: pd.DataFrame) -> pd.DataFrame:
    """行业暴露 Top5。"""
    rows = []
    for strategy, group in holdings.groupby("strategy"):
        dist = group["industry_level1"].value_counts(normalize=True).head(5)
        rows.append({"策略": strategy, "行业暴露Top5": "; ".join(f"{k}:{v:.1%}" for k, v in dist.items())})
    return pd.DataFrame(rows)


def summarize_market_cap(holdings: pd.DataFrame) -> pd.DataFrame:
    """市值代理分桶暴露。"""
    data = holdings.dropna(subset=["market_cap_proxy"]).copy()
    rows = []
    if data.empty:
        return pd.DataFrame(columns=["策略", "市值中位数代理", "市值分布"])
    data["market_cap_bucket"] = bucket_market_cap(data["market_cap_proxy"])
    for strategy, group in data.groupby("strategy"):
        dist = group["market_cap_bucket"].value_counts(normalize=True)
        rows.append(
            {
                "策略": strategy,
                "市值中位数代理": float(group["market_cap_proxy"].median()),
                "市值分布": "; ".join(f"{k}:{v:.1%}" for k, v in dist.items()),
            }
        )
    return pd.DataFrame(rows)


def format_percent(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """格式化百分比列。"""
    result = frame.copy()
    for column in columns:
        result[column] = result[column].map(lambda value: "" if pd.isna(value) else f"{value:.2%}")
    return result


def format_float(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化浮点列。"""
    result = frame.copy()
    for column in result.columns:
        if pd.api.types.is_float_dtype(result[column]):
            result[column] = result[column].map(lambda value: "" if pd.isna(value) else f"{value:.3f}")
    return result


def classify_regime(benchmark_annual: pd.DataFrame) -> pd.DataFrame:
    """用基准年度收益粗分牛熊震荡，仅用于解释年度贡献。"""
    result = benchmark_annual.copy()
    result["市场状态"] = result["收益"].map(lambda x: "牛市" if x > 0.15 else ("熊市" if x < -0.10 else "震荡市"))
    return result[["年份", "市场状态"]]


def render_report(tables: dict[str, pd.DataFrame], conclusions: dict[str, str]) -> str:
    """渲染归因报告。"""
    return f"""# Quality Alpha Attribution（Quality Alpha V2）

## 研究边界

- 不新增策略，不新增因子，不调参数，不优化收益。
- Quality V1 固定为 ROE、ROA、OCF_TO_OR 等权，Top20，月频。
- 执行层固定 M0 ExecutionModel，风险层固定 20日波动率 > 45% 降至 30%。

## 1. Quality V1 vs 单因子 vs 双因子

{markdown_table(format_float(format_percent(tables["metrics"], ["年化收益", "最大回撤", "总收益", "基准收益", "超额收益"])))}

## 2. 行业暴露

{markdown_table(tables["industry"])}

## 3. 市值暴露

{markdown_table(format_float(tables["market_cap"]))}

## 4. Marginal Contribution

{markdown_table(format_float(format_percent(tables["marginal"], ["最大回撤变化", "超额收益变化"])))}

## 5. 因子相关性

### Pearson

{markdown_table(format_float(tables["pearson"].reset_index().rename(columns={"index": "因子"})))}

### Spearman

{markdown_table(format_float(tables["spearman"].reset_index().rename(columns={"index": "因子"})))}

## 6. 持仓、行业、收益相关性

{markdown_table(format_percent(tables["overlap"], ["持仓重叠率", "行业重叠率", "收益相关性"]))}

## 7. 年度贡献

{markdown_table(format_percent(tables["annual"], ["收益", "最大回撤"]))}

## 8. 牛熊震荡结论

{markdown_table(tables["regime_best"])}

## 最终回答

1. Quality Alpha 真正核心 Alpha：{conclusions["core_alpha"]}
2. 可以删除且影响较小的因子：{conclusions["removable_factor"]}
3. 噪声因子判断：{conclusions["noise_factor"]}
4. Quality Alpha V2 建议：{conclusions["v2_recommendation"]}
"""


def build_conclusions(metrics: pd.DataFrame, marginal: pd.DataFrame) -> dict[str, str]:
    """根据归因结果生成审慎结论。"""
    best_single = metrics[metrics["策略"].str.endswith("Only")].sort_values(["夏普", "Calmar"], ascending=False).iloc[0]
    best_pair = metrics[metrics["策略"].str.contains("\\+")].sort_values(["夏普", "Calmar"], ascending=False).iloc[0]
    removable = marginal.assign(score=marginal[["Sharpe变化", "Calmar变化", "超额收益变化"]].abs().sum(axis=1)).sort_values("score").iloc[0]
    noise = marginal[(marginal["Sharpe变化"] >= 0) & (marginal["Calmar变化"] >= 0) & (marginal["超额收益变化"] >= 0)]
    return {
        "core_alpha": f"不是单一因子独占。最强单因子是 {best_single['策略']}，最接近 Quality V1 的双因子是 {best_pair['策略']}，需要结合边际贡献判断三者是否互补。",
        "removable_factor": f"{removable['删除项'].replace('删除', '')} 的边际影响最小，对应退化策略为 {removable['退化策略']}。",
        "noise_factor": "未发现删除后 Sharpe、Calmar、超额收益同时改善的明确噪声因子。" if noise.empty else f"{noise.iloc[0]['删除项'].replace('删除', '')} 有噪声嫌疑。",
        "v2_recommendation": "若追求解释简洁，可优先验证最接近 Quality V1 的双因子；若追求稳健解释，当前不应直接删除第三个因子。",
    }


def main() -> None:
    """运行 Quality Alpha Attribution V2。"""
    con = open_live_market_connection(DB_PATH, INCREMENT_PATH)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        create_annual_valuation_asof_table(con)
        candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        benchmark, _, _ = load_dashboard_benchmarks(con)
        calendar = load_calendar(con)
        results = {}
        selections_by_strategy = {}
        holdings_list = []
        for name, factors in FACTOR_VARIANTS.items():
            selections, holdings = build_selections(candidates, factors)
            all_symbols = sorted({symbol for symbols in selections.values() for symbol in symbols})
            bars = load_research_bars(con, all_symbols)
            targets = {date: {symbol: 1.0 / len(symbols) for symbol in symbols} for date, symbols in selections.items() if symbols}
            run = run_risk_layer_backtest(
                name,
                "GRID",
                targets,
                bars,
                calendar,
                benchmark,
                ExecutionModel(slippage_bps=5.0),
                vol_window=VOL_WINDOW,
                vol_threshold=VOL_THRESHOLD,
                reduced_exposure=REDUCED_EXPOSURE,
            )
            results[name] = run.result
            selections_by_strategy[name] = selections
            enriched = add_industry(holdings)
            enriched["strategy"] = name
            holdings_list.append(enriched)

        all_holdings = attach_valuation_exposure(con, pd.concat(holdings_list, ignore_index=True))
        metrics = pd.DataFrame([{"策略": name, **calculate_metrics(result.daily_values, benchmark)} for name, result in results.items()])
        metric_order = ["Quality V1", "ROE Only", "ROA Only", "OCF_TO_OR Only", "ROE + ROA", "ROE + OCF_TO_OR", "ROA + OCF_TO_OR"]
        metrics["order"] = metrics["策略"].map({name: i for i, name in enumerate(metric_order)})
        metrics = metrics.sort_values("order").drop(columns=["order"])
        marginal = build_marginal_contribution(
            metrics,
            {"删除ROE": "ROA + OCF_TO_OR", "删除ROA": "ROE + OCF_TO_OR", "删除OCF_TO_OR": "ROE + ROA"},
        )
        corr = build_factor_correlation(candidates, QUALITY_COLUMNS)
        returns = pd.DataFrame({name: result.daily_values.pct_change() for name, result in results.items()}).dropna()
        overlap_rows = []
        quality_holdings = all_holdings[all_holdings["strategy"].eq("Quality V1")]
        for name in metric_order:
            current = all_holdings[all_holdings["strategy"].eq(name)]
            overlap_rows.append(
                {
                    "策略": name,
                    "持仓重叠率": average_holding_overlap(selections_by_strategy["Quality V1"], selections_by_strategy[name]),
                    "行业重叠率": average_industry_overlap(quality_holdings, current),
                    "收益相关性": float(returns["Quality V1"].corr(returns[name])) if name in returns else 1.0,
                }
            )
        annual_rows = []
        for name, result in results.items():
            annual = annual_return_drawdown(result.daily_values)
            annual["策略"] = name
            annual_rows.append(annual)
        annual = pd.concat(annual_rows, ignore_index=True)[["年份", "策略", "收益", "最大回撤"]]
        benchmark_annual = annual_return_drawdown(benchmark)
        regime = classify_regime(benchmark_annual)
        annual_regime = annual.merge(regime, on="年份", how="left")
        regime_best = (
            annual_regime.groupby(["市场状态", "策略"])["收益"].mean().reset_index().sort_values(["市场状态", "收益"], ascending=[True, False]).groupby("市场状态").head(1)
        )
        tables = {
            "metrics": metrics,
            "industry": summarize_industry(all_holdings),
            "market_cap": summarize_market_cap(all_holdings),
            "marginal": marginal,
            "pearson": corr["pearson"],
            "spearman": corr["spearman"],
            "overlap": pd.DataFrame(overlap_rows),
            "annual": annual,
            "regime_best": regime_best,
        }
        report = render_report(tables, build_conclusions(metrics, marginal))
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(markdown_table(format_float(format_percent(metrics, ["年化收益", "最大回撤", "总收益", "基准收益", "超额收益"]))))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
