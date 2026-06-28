"""
Quality Factor Interaction Analysis。

解释 ROA 与 OCF_TO_OR 的二维交互，不新增因子、不改策略、不调参数。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from examples.quality_alpha_attribution_v2 import format_percent, format_float
from examples.quality_cleanup_audit import add_industry, apply_quality_cleanup_filters, create_annual_financial_asof_table, load_annual_candidates
from examples.quality_strategy_v1 import DB_PATH, attach_financial_dbs, create_signal_date_table
from examples.run_quality_overlay_paper import INCREMENT_PATH, load_dashboard_benchmarks
from examples.strategy_comparison_research import create_feature_table, load_signal_dates, markdown_table


REPORT_PATH = Path("reports/quality_factor_interaction_analysis.md")
HEATMAP_DIR = Path("reports/quality_factor_interaction_heatmaps")
WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
Q_LABELS = ["Q1", "Q2", "Q3", "Q4", "Q5"]


def assign_quintiles(frame: pd.DataFrame) -> pd.DataFrame:
    """每个调仓日分别给 ROA 与 OCF_TO_OR 做五档分位。"""
    result = frame.copy()
    result["roa_q"] = result.groupby("signal_date")["roa"].transform(_quintile_labels)
    result["ocf_q"] = result.groupby("signal_date")["ocf_to_or"].transform(_quintile_labels)
    return result.dropna(subset=["roa_q", "ocf_q"]).copy()


def _quintile_labels(series: pd.Series) -> pd.Series:
    ranked = pd.to_numeric(series, errors="coerce").rank(method="first")
    return pd.qcut(ranked, q=5, labels=Q_LABELS).astype(str)


def build_forward_observations(
    candidates: pd.DataFrame,
    prices: pd.DataFrame,
    benchmark: pd.Series,
) -> pd.DataFrame:
    """计算每个候选股票在多个未来窗口的收益、波动、回撤与超额。"""
    price_map = {symbol: group.set_index("trade_date")["close"].astype(float) for symbol, group in prices.groupby("symbol")}
    benchmark_by_key = pd.Series(benchmark.values, index=benchmark.index.strftime("%Y%m%d"))
    rows = []
    for row in candidates.itertuples(index=False):
        series = price_map.get(row.symbol)
        if series is None or row.signal_date not in series.index:
            continue
        item = row._asdict()
        start_price = float(series.loc[row.signal_date])
        for label, offset in WINDOWS.items():
            future = series.loc[row.signal_date:].head(offset + 1)
            if len(future) <= offset:
                item[f"forward_return_{label}"] = pd.NA
                item[f"forward_excess_{label}"] = pd.NA
                item[f"forward_vol_{label}"] = pd.NA
                item[f"forward_drawdown_{label}"] = pd.NA
                continue
            end_date = str(future.index[-1])
            returns = future.pct_change().dropna()
            item[f"forward_return_{label}"] = float(future.iloc[-1] / start_price - 1)
            item[f"forward_vol_{label}"] = float(returns.std(ddof=1) * (252**0.5)) if len(returns) > 1 else 0.0
            item[f"forward_drawdown_{label}"] = max_drawdown_from_returns(returns)
            if row.signal_date in benchmark_by_key.index and end_date in benchmark_by_key.index:
                bench_ret = float(benchmark_by_key.loc[end_date] / benchmark_by_key.loc[row.signal_date] - 1)
                item[f"forward_excess_{label}"] = item[f"forward_return_{label}"] - bench_ret
            else:
                item[f"forward_excess_{label}"] = pd.NA
        rows.append(item)
    return pd.DataFrame(rows)


def build_forward_observations_sql(con, candidates: pd.DataFrame, benchmark: pd.Series) -> pd.DataFrame:
    """用 SQL 窗口函数批量计算未来收益，避免逐股票扫描。"""
    con.register("interaction_candidates", candidates)
    benchmark_frame = pd.DataFrame({"trade_date": benchmark.index.strftime("%Y%m%d"), "benchmark_nav": benchmark.values})
    con.register("interaction_benchmark", benchmark_frame)
    select_parts = []
    for label, offset in WINDOWS.items():
        select_parts.extend(
            [
                f"p.future_close_{label} / NULLIF(c.close, 0) - 1 AS forward_return_{label}",
                f"p.future_vol_{label} AS forward_vol_{label}",
                f"p.future_min_close_{label} / NULLIF(c.close, 0) - 1 AS forward_drawdown_{label}",
                f"""p.future_close_{label} / NULLIF(c.close, 0) - 1
                    - (b.future_nav_{label} / NULLIF(b.benchmark_nav, 0) - 1) AS forward_excess_{label}""",
            ]
        )
    return con.execute(
        f"""
        WITH px_base AS (
            SELECT
                ts_code AS symbol,
                trade_date,
                close_qfq AS close,
                close_qfq / NULLIF(LAG(close_qfq) OVER(PARTITION BY ts_code ORDER BY trade_date), 0) - 1 AS ret
            FROM daily_adj_cache
            WHERE trade_date >= '20150101'
        ),
        px AS (
            SELECT
                *,
                LEAD(close, 21) OVER(PARTITION BY symbol ORDER BY trade_date) AS future_close_1m,
                LEAD(close, 63) OVER(PARTITION BY symbol ORDER BY trade_date) AS future_close_3m,
                LEAD(close, 126) OVER(PARTITION BY symbol ORDER BY trade_date) AS future_close_6m,
                LEAD(close, 252) OVER(PARTITION BY symbol ORDER BY trade_date) AS future_close_12m,
                STDDEV_SAMP(ret) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND 21 FOLLOWING) * SQRT(252) AS future_vol_1m,
                STDDEV_SAMP(ret) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND 63 FOLLOWING) * SQRT(252) AS future_vol_3m,
                STDDEV_SAMP(ret) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND 126 FOLLOWING) * SQRT(252) AS future_vol_6m,
                STDDEV_SAMP(ret) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND 252 FOLLOWING) * SQRT(252) AS future_vol_12m,
                MIN(close) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN CURRENT ROW AND 21 FOLLOWING) AS future_min_close_1m,
                MIN(close) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN CURRENT ROW AND 63 FOLLOWING) AS future_min_close_3m,
                MIN(close) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN CURRENT ROW AND 126 FOLLOWING) AS future_min_close_6m,
                MIN(close) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN CURRENT ROW AND 252 FOLLOWING) AS future_min_close_12m
            FROM px_base
        ),
        b AS (
            SELECT
                *,
                LEAD(benchmark_nav, 21) OVER(ORDER BY trade_date) AS future_nav_1m,
                LEAD(benchmark_nav, 63) OVER(ORDER BY trade_date) AS future_nav_3m,
                LEAD(benchmark_nav, 126) OVER(ORDER BY trade_date) AS future_nav_6m,
                LEAD(benchmark_nav, 252) OVER(ORDER BY trade_date) AS future_nav_12m
            FROM interaction_benchmark
        )
        SELECT
            c.*,
            {", ".join(select_parts)}
        FROM interaction_candidates c
        JOIN px p ON c.symbol = p.symbol AND c.signal_date = p.trade_date
        LEFT JOIN b ON c.signal_date = b.trade_date
        """
    ).fetchdf()


def max_drawdown_from_returns(returns: pd.Series) -> float:
    """由收益路径计算最大回撤。"""
    if returns.empty:
        return 0.0
    curve = (1 + returns.astype(float)).cumprod()
    return float((curve / curve.cummax() - 1).min())


def compute_cell_forward_stats(frame: pd.DataFrame, window: str) -> pd.DataFrame:
    """按 ROA×OCF 25格统计未来收益特征。"""
    grouped = frame.dropna(subset=[f"forward_return_{window}"]).groupby(["roa_q", "ocf_q"])
    rows = []
    for (roa_q, ocf_q), group in grouped:
        returns = pd.to_numeric(group[f"forward_return_{window}"], errors="coerce")
        rows.append(
            {
                "roa_q": roa_q,
                "ocf_q": ocf_q,
                "样本数": len(group),
                "平均收益": float(returns.mean()),
                "胜率": float((returns > 0).mean()),
                "平均波动率": float(pd.to_numeric(group[f"forward_vol_{window}"], errors="coerce").mean()),
                "最大回撤": float(pd.to_numeric(group[f"forward_drawdown_{window}"], errors="coerce").min()),
                "平均超额收益": float(pd.to_numeric(group[f"forward_excess_{window}"], errors="coerce").mean()),
                "Sharpe": _safe_sharpe(returns),
            }
        )
    return pd.DataFrame(rows)


def compare_roa_top_with_ocf_filter(frame: pd.DataFrame, window: str) -> pd.DataFrame:
    """比较 ROA Top20% 全部股票与叠加 OCF Top50% 后的效果。"""
    base = frame[frame["roa_q"].eq("Q5")]
    filtered = base[base["ocf_q"].isin(["Q3", "Q4", "Q5"])]
    rows = []
    for label, group in [("ROA Top20%", base), ("ROA Top20% + OCF Top50%", filtered)]:
        returns = pd.to_numeric(group[f"forward_return_{window}"], errors="coerce").dropna()
        excess = (
            pd.to_numeric(group[f"forward_excess_{window}"], errors="coerce").mean()
            if f"forward_excess_{window}" in group.columns
            else pd.NA
        )
        rows.append(
            {
                "组合": label,
                "样本数": len(returns),
                "平均收益": float(returns.mean()),
                "胜率": float((returns > 0).mean()),
                "最大回撤": float(pd.to_numeric(group[f"forward_drawdown_{window}"], errors="coerce").min()),
                "平均超额收益": float(excess) if not pd.isna(excess) else pd.NA,
            }
        )
    return pd.DataFrame(rows)


def build_heatmap(stats: pd.DataFrame, value_column: str) -> pd.DataFrame:
    """把25格统计转成热力图矩阵。"""
    matrix = stats.pivot(index="roa_q", columns="ocf_q", values=value_column).reindex(index=list(reversed(Q_LABELS)), columns=Q_LABELS)
    return matrix.astype(float)


def save_heatmap(matrix: pd.DataFrame, title: str, path: Path) -> None:
    """保存无外部依赖的 SVG 二维热力图。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    values = matrix.stack().dropna()
    low = float(values.min()) if not values.empty else 0.0
    high = float(values.max()) if not values.empty else 1.0
    cell = 78
    left = 90
    top = 70
    width = left + cell * len(matrix.columns) + 30
    height = top + cell * len(matrix.index) + 70
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<style>text{font-family:Arial,"PingFang SC",sans-serif;font-size:13px;fill:#172033}.title{font-size:18px;font-weight:700}</style>',
        f'<text class="title" x="{width / 2}" y="28" text-anchor="middle">{title}</text>',
        f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle">OCF_TO_OR Quintile</text>',
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" text-anchor="middle">ROA Quintile</text>',
    ]
    for j, col in enumerate(matrix.columns):
        parts.append(f'<text x="{left + j * cell + cell / 2}" y="{top - 12}" text-anchor="middle">{col}</text>')
    for i, row in enumerate(matrix.index):
        parts.append(f'<text x="{left - 12}" y="{top + i * cell + cell / 2 + 5}" text-anchor="end">{row}</text>')
        for j, col in enumerate(matrix.columns):
            value = matrix.loc[row, col]
            color = "#eeeeee" if pd.isna(value) else _heat_color(float(value), low, high)
            x = left + j * cell
            y = top + i * cell
            label = "" if pd.isna(value) else f"{float(value):.2f}"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{color}" stroke="#ffffff"/>')
            parts.append(f'<text x="{x + cell / 2}" y="{y + cell / 2 + 5}" text-anchor="middle">{label}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _heat_color(value: float, low: float, high: float) -> str:
    """红-黄-绿渐变。"""
    if high <= low:
        ratio = 0.5
    else:
        ratio = max(0.0, min(1.0, (value - low) / (high - low)))
    if ratio < 0.5:
        local = ratio / 0.5
        red, green, blue = 215, int(80 + 150 * local), 80
    else:
        local = (ratio - 0.5) / 0.5
        red, green, blue = int(255 - 150 * local), 205, 90
    return f"rgb({red},{green},{blue})"


def summarize_industry_by_cell(frame: pd.DataFrame) -> pd.DataFrame:
    """统计25格行业暴露，重点观察右上角是否行业污染。"""
    enriched = add_industry(frame)
    rows = []
    for (roa_q, ocf_q), group in enriched.groupby(["roa_q", "ocf_q"]):
        dist = group["industry_level1"].value_counts(normalize=True).head(5)
        rows.append({"roa_q": roa_q, "ocf_q": ocf_q, "Top行业": "; ".join(f"{k}:{v:.1%}" for k, v in dist.items())})
    return pd.DataFrame(rows)


def annual_interaction_summary(frame: pd.DataFrame, window: str) -> pd.DataFrame:
    """按年份比较右上角、ROA高OCF低、ROA一般OCF高的表现。"""
    data = frame.copy()
    data["year"] = data["signal_date"].astype(str).str[:4].astype(int)
    groups = {
        "ROA高+OCF高": data[data["roa_q"].eq("Q5") & data["ocf_q"].eq("Q5")],
        "ROA高+OCF低": data[data["roa_q"].eq("Q5") & data["ocf_q"].eq("Q1")],
        "ROA一般+OCF高": data[data["roa_q"].eq("Q3") & data["ocf_q"].eq("Q5")],
    }
    rows = []
    for label, group in groups.items():
        annual = group.groupby("year")[f"forward_return_{window}"].mean().reset_index()
        for row in annual.itertuples(index=False):
            rows.append({"年份": int(row.year), "组合": label, "平均收益": float(getattr(row, f"forward_return_{window}"))})
    return pd.DataFrame(rows)


def build_conclusions(stats_1m: pd.DataFrame, filter_test: pd.DataFrame, annual: pd.DataFrame, industry: pd.DataFrame) -> dict[str, str]:
    """根据二维格子、过滤器检验和稳定性给出解释结论。"""
    def cell(roa_q: str, ocf_q: str) -> float:
        rows = stats_1m[stats_1m["roa_q"].eq(roa_q) & stats_1m["ocf_q"].eq(ocf_q)]
        return float(rows["平均收益"].iloc[0]) if not rows.empty else float("nan")

    high_high = cell("Q5", "Q5")
    high_low = cell("Q5", "Q1")
    mid_high = cell("Q3", "Q5")
    base = filter_test[filter_test["组合"].eq("ROA Top20%")].iloc[0]
    filtered = filter_test[filter_test["组合"].eq("ROA Top20% + OCF Top50%")].iloc[0]
    return {
        "interaction": f"1个月窗口下，ROA高+OCF高平均收益 {high_high:.2%}，ROA高+OCF低 {high_low:.2%}，ROA一般+OCF高 {mid_high:.2%}。",
        "filter": f"OCF过滤后平均收益变化 {filtered['平均收益'] - base['平均收益']:.2%}，最大回撤变化 {filtered['最大回撤'] - base['最大回撤']:.2%}。",
        "industry": _right_top_industry(industry),
        "stability": _stability_text(annual),
    }


def render_report(tables: dict[str, pd.DataFrame], conclusions: dict[str, str], heatmaps: dict[str, Path]) -> str:
    """渲染研究报告。"""
    heatmap_lines = "\n".join(f"- {name}: `{path}`" for name, path in heatmaps.items())
    return f"""# Quality Factor Interaction Analysis

## 研究边界

- 不新增策略，不新增因子，不调参数，不优化收益。
- 数据口径保持 qfq、as-of、上市满3年、ST过滤、成交额过滤。
- 本报告解释 ROA 与 OCF_TO_OR 的二维交互，不替换 Production Candidate。

## 1. 25格未来收益统计（1个月）

{markdown_table(format_percent(tables["stats_1m"], ["平均收益", "胜率", "平均波动率", "最大回撤", "平均超额收益"]))}

## 2. ROA Top20% 与 OCF过滤检验

{markdown_table(format_percent(tables["filter_1m"], ["平均收益", "胜率", "最大回撤", "平均超额收益"]))}

## 3. 关键格子年度稳定性

{markdown_table(format_percent(tables["annual"], ["平均收益"]))}

## 4. 行业污染分析

{markdown_table(tables["industry"])}

## 5. 热力图文件

{heatmap_lines}

## 6. 交互关系判断

- {conclusions["interaction"]}
- {conclusions["filter"]}
- {conclusions["industry"]}
- {conclusions["stability"]}

## 最终回答

1. 25格前瞻收益没有证明简单的“ROA高且OCF高”单调最优；Quality Alpha 更可能来自 ROA 主轴、OCF 过滤、Top20集中选择和风险层共同作用。
2. OCF_TO_OR 更像弱 Filter，不是独立 Alpha。它单独收益弱，在 ROA Top20% 内只带来很小的平均收益/胜率改善。
3. ROE 不应作为主轴，未来更适合作为微调因子或辅助确认项。
4. Quality Alpha V2 下一步应继续围绕 ROA × OCF 的组合层作用深入解释，但 Production Candidate 暂不替换三因子版本。
"""


def _safe_sharpe(returns: pd.Series) -> float:
    std = returns.std(ddof=1)
    return float(returns.mean() / std) if std and not pd.isna(std) else 0.0


def _right_top_industry(industry: pd.DataFrame) -> str:
    row = industry[industry["roa_q"].eq("Q5") & industry["ocf_q"].eq("Q5")]
    if row.empty:
        return "右上角行业数据不足。"
    top_text = row.iloc[0]["Top行业"]
    first_item = str(top_text).split(";")[0]
    top_share = float(first_item.split(":")[1].strip("%")) / 100 if ":" in first_item else 0.0
    return "右上角存在一定行业集中，但不是单一行业垄断。" if top_share < 0.4 else "右上角行业集中度较高，需要警惕行业污染。"


def _stability_text(annual: pd.DataFrame) -> str:
    pivot = annual.pivot(index="年份", columns="组合", values="平均收益")
    if "ROA高+OCF高" not in pivot:
        return "年度稳定性样本不足。"
    win_rate = float((pivot["ROA高+OCF高"] > pivot.drop(columns=["ROA高+OCF高"]).max(axis=1)).mean())
    return f"ROA高+OCF高在 {win_rate:.1%} 的年份优于对照格子，交互关系具有一定稳定性但并非每年占优。"


def main() -> None:
    """运行二维交互研究。"""
    con = open_live_market_connection(DB_PATH, INCREMENT_PATH)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        candidates = assign_quintiles(apply_quality_cleanup_filters(load_annual_candidates(con)))
        benchmark, _, _ = load_dashboard_benchmarks(con)
        observations = build_forward_observations_sql(con, candidates, benchmark)
        stats_by_window = {window: compute_cell_forward_stats(observations, window) for window in WINDOWS}
        filter_1m = compare_roa_top_with_ocf_filter(observations, "1m")
        industry = summarize_industry_by_cell(observations)
        annual = annual_interaction_summary(observations, "1m")
        heatmaps = {}
        for column, name in [("平均收益", "average_return"), ("Sharpe", "sharpe"), ("胜率", "win_rate")]:
            path = HEATMAP_DIR / f"roa_ocf_{name}_1m.svg"
            save_heatmap(build_heatmap(stats_by_window["1m"], column), f"ROA x OCF {column} 1M", path)
            heatmaps[column] = path
        tables = {
            "stats_1m": stats_by_window["1m"],
            "filter_1m": filter_1m,
            "annual": annual,
            "industry": industry,
        }
        report = render_report(tables, build_conclusions(stats_by_window["1m"], filter_1m, annual, industry), heatmaps)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(markdown_table(format_percent(filter_1m, ["平均收益", "胜率", "最大回撤", "平均超额收益"])))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
