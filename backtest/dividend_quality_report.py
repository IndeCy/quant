"""Dividend Quality 报告渲染。"""

from __future__ import annotations

import pandas as pd

from examples.strategy_comparison_research import format_percent, markdown_table


def format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化回测指标。"""
    formatted = frame.copy()
    percent_columns = ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益"]
    for column in percent_columns:
        formatted[column] = formatted[column].map(format_percent)
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    if "Calmar" in formatted.columns:
        formatted["Calmar"] = formatted["Calmar"].map(lambda value: f"{value:.2f}")
    return formatted


def render_dividend_quality_report(
    audit: dict[str, object],
    source_coverage: pd.DataFrame,
    coverage: pd.DataFrame,
    metrics: pd.DataFrame,
    industry_dist: pd.DataFrame,
    size_dist: pd.DataFrame,
    latest_holdings: pd.DataFrame,
    strategy_label: str = "Dividend Quality V1",
    asof_note: str = "仅使用 `f_ann_date <= signal_date` 的 1231 年报数据。",
    dividend_note: str = (
        "当前 V1 使用 `COALESCE(comshare_payable_dvd, div_payt) / 市值代理`，"
        "不是标准 trailing cash dividend yield。"
    ),
    conclusion: str | None = None,
    next_step_note: str | None = None,
    risk_notes: list[str] | None = None,
) -> str:
    """生成 Dividend Quality Markdown 报告。"""
    latest_view = _format_latest_holdings(latest_holdings)
    final_conclusion = conclusion or (
        "当前 V1 不构成可上线策略：分红代理覆盖过低，组合长期不足20只，"
        "更像是在验证数据缺口，而不是验证稳定红利因子。"
    )
    follow_up = next_step_note or (
        "当前结果不能证明收益来自红利或质量。若后续补齐标准分红实施表，再重新验证\n"
        "trailing dividend yield、连续分红和支付率，才适合判断红利质量因子是否有效。"
    )
    final_risk_notes = risk_notes or [
        "标准分红明细表缺失，无法验证真实除权除息口径、连续分红和滚动股息率。",
        "`comshare_payable_dvd/div_payt` 来自财报科目，覆盖低且存在会计口径和单位口径偏差。",
        "行业覆盖仍依赖项目内置行业映射，未知行业可能影响行业暴露判断。",
        "下一步应优先补齐标准 `dividend` / 分红实施公告表，再升级 Dividend Quality V2。",
    ]
    risk_block = "\n".join(f"- {note}" for note in final_risk_notes)
    return f"""# {strategy_label} 研究报告

## 数据审计

- 标准分红表：{'有' if audit['has_standard_dividend_table'] else '无'}
- 可用分红代理字段：{', '.join(audit['proxy_fields']) if audit['proxy_fields'] else '无'}
- as-of 口径：{asof_note}
- 分红口径：{dividend_note}

{markdown_table(source_coverage.head(20))}

## 分红覆盖度

{markdown_table(coverage.tail(12))}

## 策略定义

- 股票池：上市满3年，剔除 ST/*ST/退市，剔除成交额最低20%，必须有分红代理记录。
- 因子：40% 股息率代理，30% ROE/ROA 质量，30% OCF_TO_OR 现金流质量。
- 约束：支付率 0~120%，资产负债率不高于85%，股息率和支付率按月横截面缩尾。
- 调仓：月频 Top20 等权。
- 成交：复用 M0 `ExecutionModel`，T日信号、T+1交易日成交。
- 基准：510300 ETF 复权口径。

## 回测结果

{markdown_table(format_metrics(metrics))}

## 行业分布

{markdown_table(industry_dist.head(20))}

## 市值分布

{markdown_table(size_dist)}

## 最新一期持仓

{markdown_table(latest_view)}

## 归因判断

{final_conclusion}

{follow_up}

## 风险与后续

{risk_block}
"""


def _format_latest_holdings(latest_holdings: pd.DataFrame) -> pd.DataFrame:
    """格式化最新持仓表。"""
    latest_cols = [
        "rank", "symbol", "name", "dividend_yield_proxy", "payout_ratio",
        "roe", "roa", "ocf_to_or", "debt_to_assets", "industry_level1",
    ]
    latest_view = latest_holdings[[column for column in latest_cols if column in latest_holdings.columns]].copy()
    for column in ["dividend_yield_proxy", "payout_ratio"]:
        if column in latest_view.columns:
            latest_view[column] = latest_view[column].map(lambda value: f"{value:.2%}")
    for column in ["roe", "roa", "ocf_to_or", "debt_to_assets"]:
        if column in latest_view.columns:
            latest_view[column] = latest_view[column].map(lambda value: f"{value:.2f}")
    return latest_view
