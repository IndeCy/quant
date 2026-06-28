"""
Cash Cow V1.5 口径修复验证。

只验证三项修复：OCF_TO_NP 分母陷阱、多年现金流稳定性、行业污染。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.cash_cow_report import (
    add_exposures,
    calculate_calmar,
    drawdown_window,
    return_correlation,
    summarize_distribution,
)
from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import load_hs300_benchmark
from examples.cash_cow_v1 import (
    apply_cash_cow_filters,
    audit_cash_cow_fields,
    build_cash_cow_selections,
    calculate_overlap,
    create_cash_cow_asof_table,
    load_cash_cow_candidates,
)
from examples.quality_cleanup_audit import (
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_strategy_v1 import FUND_BASIC_PATH, FUND_DAILY_PATH, attach_financial_dbs, create_signal_date_table
from examples.strategy_comparison_research import (
    START_DATE,
    build_metrics_table,
    create_feature_table,
    format_percent,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    run_monthly_backtest,
)


REPORT_PATH = Path("reports/cash_cow_v15.md")
HOLDINGS_PATH = Path("reports/cash_cow_v15_holdings.csv")
CONTAMINATED_KEYWORDS = ["地产", "水运", "小金属", "石油", "煤炭", "钢铁", "有色", "种植业"]


def create_cash_cow_v15_asof_table(con) -> None:
    """构造带过去3年 OCF/FCF 稳定性统计的 as-of 表。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE financial_cash_cow_v15_asof AS
        WITH publish_dates AS (
            SELECT ts_code, end_date, MAX(f_ann_date) AS f_ann_date
            FROM (
                SELECT ts_code, end_date, f_ann_date FROM income_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM balance_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM cashflow_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, ann_date AS f_ann_date FROM fina_db.default_table WHERE ann_date IS NOT NULL
            )
            WHERE RIGHT(end_date, 4) = '1231'
            GROUP BY ts_code, end_date
        ),
        annual AS (
            SELECT
                p.ts_code AS symbol,
                p.end_date,
                p.f_ann_date,
                CAST(f.ocf_to_or AS DOUBLE) AS ocf_to_or,
                CAST(f.debt_to_assets AS DOUBLE) AS debt_to_assets,
                CAST(i.revenue AS DOUBLE) AS revenue,
                CAST(i.n_income_attr_p AS DOUBLE) AS n_income_attr_p,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
                CAST(c.n_cashflow_act AS DOUBLE) AS n_cashflow_act,
                CAST(c.c_pay_acq_const_fiolta AS DOUBLE) AS c_pay_acq_const_fiolta,
                c.n_cashflow_act / NULLIF(i.n_income_attr_p, 0) AS ocf_to_np,
                c.n_cashflow_act - c.c_pay_acq_const_fiolta AS fcf,
                (c.n_cashflow_act - c.c_pay_acq_const_fiolta) / NULLIF(b.total_assets, 0) AS fcf_to_assets,
                i.n_income_attr_p / NULLIF(i.revenue, 0) AS net_profit_margin
            FROM publish_dates p
            JOIN fina_db.default_table f ON p.ts_code = f.ts_code AND p.end_date = f.end_date
            JOIN income_db.default_table i ON p.ts_code = i.ts_code AND p.end_date = i.end_date
            JOIN balance_db.default_table b ON p.ts_code = b.ts_code AND p.end_date = b.end_date
            JOIN cashflow_db.default_table c ON p.ts_code = c.ts_code AND p.end_date = c.end_date
        ),
        latest AS (
            SELECT
                d.signal_date,
                a.*,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, a.symbol
                    ORDER BY a.end_date DESC, a.f_ann_date DESC
                ) AS rn
            FROM quality_signal_dates d
            JOIN annual a ON a.f_ann_date <= d.signal_date
        ),
        history AS (
            SELECT
                d.signal_date,
                a.symbol,
                a.end_date,
                CASE WHEN a.n_cashflow_act > 0 THEN 1 ELSE 0 END AS ocf_positive,
                CASE WHEN a.fcf > 0 THEN 1 ELSE 0 END AS fcf_positive,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, a.symbol
                    ORDER BY a.end_date DESC, a.f_ann_date DESC
                ) AS rn
            FROM quality_signal_dates d
            JOIN annual a ON a.f_ann_date <= d.signal_date
        ),
        stability AS (
            SELECT
                signal_date,
                symbol,
                SUM(ocf_positive) AS ocf_positive_years_3,
                SUM(fcf_positive) AS fcf_positive_years_3,
                COUNT(*) AS available_years_3
            FROM history
            WHERE rn <= 3
            GROUP BY signal_date, symbol
        )
        SELECT l.*, s.ocf_positive_years_3, s.fcf_positive_years_3, s.available_years_3
        FROM latest l
        JOIN stability s ON l.signal_date = s.signal_date AND l.symbol = s.symbol
        WHERE l.rn = 1
        """
    )


def load_cash_cow_v15_candidates(con) -> pd.DataFrame:
    """读取 V1.5 候选池，复用 V1 的交易与上市清洗字段。"""
    create_cash_cow_asof_table(con)
    base = load_cash_cow_candidates(con)
    v15 = con.execute(
        """
        SELECT signal_date, symbol, revenue, n_income_attr_p, net_profit_margin,
               ocf_positive_years_3, fcf_positive_years_3
        FROM financial_cash_cow_v15_asof
        """
    ).fetchdf()
    return base.merge(v15, on=["signal_date", "symbol"], how="left")


def apply_v15_filters(frame: pd.DataFrame) -> pd.DataFrame:
    """修复 OCF_TO_NP 分母陷阱，并要求3年现金流稳定。"""
    data = frame.copy()
    required = ["n_income_attr_p", "revenue", "net_profit_margin", "ocf_positive_years_3", "fcf_positive_years_3"]
    for column in required:
        if column not in data.columns:
            data[column] = pd.NA
    if data["net_profit_margin"].isna().all() and {"n_income_attr_p", "revenue"} <= set(data.columns):
        data["net_profit_margin"] = pd.to_numeric(data["n_income_attr_p"], errors="coerce") / pd.to_numeric(
            data["revenue"], errors="coerce"
        ).replace(0, pd.NA)
    valid = (
        (pd.to_numeric(data["n_income_attr_p"], errors="coerce") > 0)
        & (pd.to_numeric(data["net_profit_margin"], errors="coerce") >= 0.03)
        & (pd.to_numeric(data["ocf_to_np"], errors="coerce") > 0)
        & (pd.to_numeric(data["ocf_positive_years_3"], errors="coerce") >= 2)
        & (pd.to_numeric(data["fcf_positive_years_3"], errors="coerce") >= 2)
    )
    return data[valid].copy()


def score_cash_cow_v15_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """V1.5 核心打分移除 OCF_TO_NP，只保留现金收入质量和 FCF 资产效率。"""
    scored = frame.dropna(subset=["ocf_to_or", "fcf_to_assets"]).copy()
    scored["ocf_to_or_z"] = _zscore(_winsorize(scored["ocf_to_or"]))
    scored["fcf_to_assets_z"] = _zscore(_winsorize(scored["fcf_to_assets"]))
    scored["cash_cow_score"] = 0.5 * scored["ocf_to_or_z"] + 0.5 * scored["fcf_to_assets_z"]
    return scored.sort_values(["cash_cow_score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_v15_selections(candidates: pd.DataFrame, use_industry_cap: bool = False) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按 V1.5 打分生成 Top20，可选单行业20%上限。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_cash_cow_v15_frame(group)
        top = apply_industry_cap(scored, top_n=20, cap=0.2) if use_industry_cap else scored.head(20).copy()
        top["signal_date"] = str(signal_date)
        top["rank"] = range(1, len(top) + 1)
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    return selections, pd.concat(holdings, ignore_index=True) if holdings else pd.DataFrame()


def apply_industry_cap(frame: pd.DataFrame, top_n: int = 20, cap: float = 0.2) -> pd.DataFrame:
    """按分数顺序选择，单行业数量不超过 top_n * cap。"""
    limit = max(int(top_n * cap), 1)
    counts: dict[str, int] = {}
    rows = []
    for _, row in frame.sort_values(["cash_cow_score", "symbol"], ascending=[False, True]).iterrows():
        industry = str(row.get("industry_level1", "未知"))
        if counts.get(industry, 0) >= limit:
            continue
        rows.append(row)
        counts[industry] = counts.get(industry, 0) + 1
        if len(rows) >= top_n:
            break
    return pd.DataFrame(rows)


def remove_contaminated_industries(frame: pd.DataFrame) -> pd.DataFrame:
    """剔除地产、资源、航运等污染行业。"""
    pattern = "|".join(CONTAMINATED_KEYWORDS)
    industry = frame["industry_level1"].fillna("").astype(str)
    return frame[~industry.str.contains(pattern, regex=True)].copy()


def ocf_extreme_summary(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """统计 OCF_TO_NP 极端值和入选股票变化。"""
    return pd.DataFrame(
        [
            {"阶段": "V1候选", "样本数": len(before), "OCF_TO_NP>50": int((before["ocf_to_np"] > 50).sum()), "股票数": before["symbol"].nunique()},
            {"阶段": "V1.5过滤后", "样本数": len(after), "OCF_TO_NP>50": int((after["ocf_to_np"] > 50).sum()), "股票数": after["symbol"].nunique()},
        ]
    )


def run_variant(name: str, selections: dict[str, list[str]], bars: pd.DataFrame, calendar: list[pd.Timestamp]):
    """统一执行单个版本回测。"""
    return run_monthly_backtest(name, selections, bars, calendar, ExecutionModel(slippage_bps=5.0))


def render_report(metrics: pd.DataFrame, comparisons: pd.DataFrame, industries: dict[str, pd.DataFrame], dd_rows: pd.DataFrame, extremes: pd.DataFrame) -> str:
    """生成 V1.5 修复验证报告。"""
    formatted = metrics.copy()
    for column in ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益"]:
        formatted[column] = formatted[column].map(format_percent)
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    comp = comparisons.copy()
    comp["持仓重叠"] = comp["持仓重叠"].map(lambda value: f"{value:.2%}")
    comp["收益相关性"] = comp["收益相关性"].map(lambda value: f"{value:.2f}")
    industry_text = []
    for name, frame in industries.items():
        display = frame.copy()
        display["占比"] = display["占比"].map(lambda value: f"{value:.2%}")
        industry_text.append(f"### {name}\n\n{markdown_table(display.head(10))}")
    conclusion = _final_conclusion(metrics)
    return f"""# Cash Cow V1.5 口径修复验证

## 一、修复说明

- OCF_TO_NP 不再进入核心打分，仅作为辅助过滤：净利润 > 0，净利润率 >= 3%，OCF_TO_NP > 0。
- 新增多年稳定性过滤：过去3年中至少2年 OCF > 0，且至少2年 FCF > 0。
- 行业污染只做两个对照：剔除污染行业、单行业上限20%。

## 二、OCF_TO_NP 极端值变化

{markdown_table(extremes)}

## 三、版本回测对比

{markdown_table(formatted)}

## 四、与 Quality Alpha V1 的独立性

{markdown_table(comp)}

## 五、行业分布

{chr(10).join(industry_text)}

## 六、最大回撤区间

{markdown_table(dd_rows)}

## 七、结论

{conclusion}
"""


def main() -> None:
    """运行 Cash Cow V1.5 修复验证。"""
    import duckdb

    from examples.quality_strategy_v1 import DB_PATH

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_cash_cow_asof_table(con)
        v1_raw = load_cash_cow_candidates(con)
        v1_candidates = apply_cash_cow_filters(v1_raw)
        v1_selections, v1_holdings = build_cash_cow_selections(v1_candidates)

        create_cash_cow_v15_asof_table(con)
        v15_raw = load_cash_cow_v15_candidates(con)
        v15_base = apply_v15_filters(apply_cash_cow_filters(v15_raw))
        v15_base = add_exposures(v15_base)
        v15_selections, v15_holdings = build_v15_selections(v15_base)
        clean_base = remove_contaminated_industries(v15_base)
        clean_selections, clean_holdings = build_v15_selections(clean_base)
        cap_selections, cap_holdings = build_v15_selections(v15_base, use_industry_cap=True)

        create_annual_financial_asof_table(con)
        quality_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        quality_selections, _ = build_top20_from_candidates(quality_candidates)

        variants = {
            "Cash Cow V1 原版": (v1_selections, add_exposures(v1_holdings)),
            "Cash Cow V1.5 修复版": (v15_selections, v15_holdings),
            "V1.5 剔除污染行业": (clean_selections, clean_holdings),
            "V1.5 行业上限20%": (cap_selections, cap_holdings),
        }
        all_symbols = sorted({s for selections, _ in variants.values() for symbols in selections.values() for s in symbols} | {s for symbols in quality_selections.values() for s in symbols})
        bars = load_research_bars(con, all_symbols)
        calendar = load_calendar(con)
        results = {name: run_variant(name, selections, bars, calendar) for name, (selections, _) in variants.items()}
        quality_result = run_variant("Quality Alpha V1", quality_selections, bars, calendar)
        benchmark, _ = load_hs300_benchmark(con, START_DATE, str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None, str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None)
        metrics = build_metrics_table(results, benchmark)
        comparisons = pd.DataFrame(
            [
                {"版本": name, "持仓重叠": calculate_overlap(selections, quality_selections), "收益相关性": return_correlation(results[name].daily_values, quality_result.daily_values)}
                for name, (selections, _) in variants.items()
            ]
        )
        industries = {name: summarize_distribution(holdings, "industry_level1") for name, (_, holdings) in variants.items()}
        dd_rows = pd.DataFrame([{"版本": name, **drawdown_window(result.daily_values)} for name, result in results.items()])
        extremes = ocf_extreme_summary(v1_candidates, v15_base)
        REPORT_PATH.write_text(render_report(metrics, comparisons, industries, dd_rows, extremes), encoding="utf-8")
        pd.concat([h.assign(version=name) for name, (_, h) in variants.items()], ignore_index=True).to_csv(HOLDINGS_PATH, index=False)
        print(metrics.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


def _winsorize(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.clip(numeric.quantile(0.05), numeric.quantile(0.95))


def _zscore(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    std = numeric.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (numeric - numeric.mean()) / std


def _final_conclusion(metrics: pd.DataFrame) -> str:
    v15 = metrics[metrics["策略"].eq("Cash Cow V1.5 修复版")].iloc[0]
    if float(v15["超额收益"]) <= 0 or float(v15["最大回撤"]) < -0.55:
        return (
            "修复后仍不建议保留为长期研究分支。失败主因更像 A. 现金流因子天然容易被周期污染，"
            "叠加 B. A股里现金奶牛主线本身不强；当前数据口径虽可用，但 C. 干净度仍不足。"
            "建议终止 Cash Cow 主线，把资源转回 Dividend Quality V3 或 QARP。"
        )
    return "修复后出现改善，可作为低优先级观察分支，但仍不进入主策略。"


if __name__ == "__main__":
    main()
