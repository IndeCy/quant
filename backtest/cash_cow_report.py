"""Cash Cow 研究报告与法医分析工具。"""

from __future__ import annotations

import pandas as pd

from backtest.industry import IndustryManager
from examples.strategy_comparison_research import format_percent, markdown_table


def add_exposures(holdings: pd.DataFrame) -> pd.DataFrame:
    """补充行业和市值代理暴露。"""
    manager = IndustryManager()
    enriched = holdings.copy()
    enriched["industry_level1"] = [
        manager.get_industry_by_stock(symbol).get("level1", "未知") for symbol in enriched["symbol"]
    ]
    enriched["market_cap_proxy"] = enriched["close"].astype(float)
    enriched["market_cap_bucket"] = "未知"
    for _, group in enriched.groupby("signal_date", sort=True):
        try:
            labels = pd.qcut(group["market_cap_proxy"], 4, labels=["低价/小市值代理", "中低", "中高", "高价/大市值代理"])
            enriched.loc[group.index, "market_cap_bucket"] = labels.astype(str).values
        except ValueError:
            pass
    return enriched


def summarize_distribution(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """统计持仓暴露分布。"""
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[column, "持仓记录数", "占比"])
    result = frame.groupby(column, dropna=False).size().reset_index(name="持仓记录数")
    result["占比"] = result["持仓记录数"] / len(frame)
    return result.sort_values("持仓记录数", ascending=False)


def summarize_factor_distribution(holdings: pd.DataFrame) -> pd.DataFrame:
    """输出持仓核心财务字段分布。"""
    rows = []
    for column in ["ocf_to_or", "ocf_to_np", "fcf_to_assets", "debt_to_assets"]:
        s = pd.to_numeric(holdings[column], errors="coerce").dropna()
        rows.append({"字段": column, "均值": s.mean(), "中位数": s.median(), "P10": s.quantile(0.1), "P90": s.quantile(0.9)})
    return pd.DataFrame(rows)


def calculate_calmar(values: pd.Series) -> float:
    """计算 Calmar。"""
    if values.empty:
        return 0.0
    total_return = float(values.iloc[-1] / values.iloc[0] - 1)
    annual = (1 + total_return) ** (252 / max(len(values), 1)) - 1
    drawdown = ((values - values.expanding().max()) / values.expanding().max()).min()
    return float(annual / abs(drawdown)) if drawdown < 0 else 0.0


def drawdown_window(values: pd.Series) -> dict[str, object]:
    """定位最大回撤区间。"""
    running_max = values.expanding().max()
    drawdown = values / running_max - 1
    trough = drawdown.idxmin()
    peak = values.loc[:trough].idxmax()
    return {"开始": peak.strftime("%Y-%m-%d"), "谷底": trough.strftime("%Y-%m-%d"), "最大回撤": float(drawdown.loc[trough])}


def worst_contributors(result, holdings: pd.DataFrame) -> pd.DataFrame:
    """用成交记录近似统计最差贡献股票。"""
    trades = pd.DataFrame(result.trades)
    if trades.empty:
        return pd.DataFrame(columns=["symbol", "name", "realized_cashflow", "trade_count"])
    trades["cashflow"] = -trades["quantity"].astype(float) * trades["price"].astype(float) - trades["fee"].astype(float)
    names = holdings.drop_duplicates("symbol")[["symbol", "name"]]
    grouped = trades.groupby("symbol").agg(realized_cashflow=("cashflow", "sum"), trade_count=("symbol", "size")).reset_index()
    return grouped.merge(names, on="symbol", how="left").sort_values("realized_cashflow").head(20)


def return_correlation(first: pd.Series, second: pd.Series) -> float:
    """计算两个策略日收益相关性。"""
    frame = pd.concat([first.pct_change(), second.pct_change()], axis=1).dropna()
    if frame.empty:
        return 0.0
    return float(frame.iloc[:, 0].corr(frame.iloc[:, 1]))


def monthly_win_loss(cash_values: pd.Series, quality_values: pd.Series) -> pd.DataFrame:
    """比较 Cash Cow 与 Quality 每月胜负。"""
    rows = []
    for month, group in cash_values.groupby(cash_values.index.strftime("%Y%m")):
        quality = quality_values[quality_values.index.strftime("%Y%m") == month]
        if len(group) < 2 or len(quality) < 2:
            continue
        cash_ret = float(group.iloc[-1] / group.iloc[0] - 1)
        quality_ret = float(quality.iloc[-1] / quality.iloc[0] - 1)
        rows.append({"月份": month, "CashCow收益": cash_ret, "Quality收益": quality_ret, "胜者": "CashCow" if cash_ret > quality_ret else "Quality"})
    return pd.DataFrame(rows)


def render_cash_cow_report(
    audit: pd.DataFrame,
    metrics: pd.DataFrame,
    factor_dist: pd.DataFrame,
    industry: pd.DataFrame,
    size_dist: pd.DataFrame,
    drawdown: dict[str, object],
    worst: pd.DataFrame,
    overlap: float,
    corr: float,
    wins: pd.DataFrame,
) -> str:
    """渲染完整研究报告。"""
    metrics_display = _format_metrics(metrics)
    audit_display = audit.copy()
    audit_display["缺失率"] = audit_display["缺失率"].map(lambda value: f"{value:.2%}")
    factor_display = factor_dist.copy()
    for column in ["均值", "中位数", "P10", "P90"]:
        factor_display[column] = factor_display[column].map(lambda value: f"{value:.4f}")
    industry_display = _format_percent_columns(industry, ["占比"])
    size_display = _format_percent_columns(size_dist, ["占比"])
    win_summary = wins["胜者"].value_counts().to_dict() if not wins.empty else {}
    verdict, failure_reason = _cash_cow_verdict(metrics, overlap, corr)
    return f"""# Cash Cow V1 研究报告

## 一、财务口径审计

{markdown_table(audit_display)}

结论：本地数据具备构造 Cash Cow V1 的最低条件。`FCF = n_cashflow_act - c_pay_acq_const_fiolta`，其中资本开支映射为现金流量表 `c_pay_acq_const_fiolta`。同时保留 `free_cashflow` 做供应商口径对照，不直接替代。

主要风险：该资本开支字段是现金流出项，适合保守估算自由现金流；但周期行业在景气顶部可能同时出现高 OCF 和滞后的低资本开支，存在“伪现金牛”风险。

## 二、策略定义

- 股票池：上市满3年，剔除 ST/*ST/退市，剔除低成交额，且只使用 `1231` 年报。
- as-of：所有财务数据满足 `f_ann_date <= signal_date`。
- 因子：`OCF_TO_OR`、`OCF_TO_NP`、`FCF_TO_ASSETS`。
- 打分：5%/95% Winsorize，Z-score，固定权重 35%/35%/30%。
- 约束：资产负债率使用横截面后20%过滤，作为负向约束。
- 组合：月频 Top20 等权，M0 ExecutionModel，T+1 成交，基准为 510300 复权。

## 三、回测结果

{markdown_table(metrics_display)}

## 四、风格暴露

### 行业分布

{markdown_table(industry_display.head(15))}

### 市值代理分布

{markdown_table(size_display)}

说明：当前本地稳定可用的 PE/PB/市值日频表不足，市值分布暂用持仓价格分层代理，不作为严格市值结论。

### 财务因子分布

{markdown_table(factor_display)}

## 五、与 Quality Alpha V1 对比

- 平均持仓重叠度：{overlap:.2%}
- 日收益相关性：{corr:.2f}
- 月度胜负：{win_summary}
- 判断：如果收益相关性和重叠度不高，则不是简单“换壳 Quality”；若相关性偏高，则应谨慎作为独立主线。

## 六、Cash Cow V1 Forensics

- 最大回撤开始：{drawdown['开始']}
- 最大回撤谷底：{drawdown['谷底']}
- 最大回撤：{drawdown['最大回撤']:.2%}

### 最差贡献前20股票（按成交现金流近似）

{markdown_table(worst)}

### 周期污染判断

行业暴露需要重点检查资源、周期、公用事业是否集中。若前几大行业集中在资源/周期，Cash Cow 很可能捕捉到景气顶部现金流而非长期现金创造能力。

## 七、结论

- Cash Cow V1 是否值得继续：{verdict}。
- 主要失败归因：{failure_reason}。
- 若只做一次 V1.5 诊断，优先方向：
  1. 增加 FCF 多年稳定性约束，而不是只看最近一期。
  2. 做行业中性或资源/周期行业单独约束，防止周期顶点现金流污染。
  3. 引入 FCF 与分红/回购或资本开支再投资效率的交叉验证。
"""


def _format_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    result = metrics.copy()
    for column in ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益", "Calmar"]:
        if column in result.columns:
            result[column] = result[column].map(format_percent)
    result["夏普比率"] = result["夏普比率"].map(lambda value: f"{value:.2f}")
    return result


def _format_percent_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = result[column].map(lambda value: "" if pd.isna(value) else f"{value:.2%}")
    return result


def _cash_cow_verdict(metrics: pd.DataFrame, overlap: float, corr: float) -> tuple[str, str]:
    """基于绩效、回撤和独立性给出结论。"""
    cash = metrics[metrics["策略"].eq("Cash Cow V1")].iloc[0]
    quality = metrics[metrics["策略"].eq("Quality Alpha V1")].iloc[0]
    weak_return = float(cash["年化收益"]) < float(quality["年化收益"]) * 0.6
    worse_drawdown = float(cash["最大回撤"]) < float(quality["最大回撤"])
    negative_excess = float(cash["超额收益"]) <= 0
    if weak_return and worse_drawdown and negative_excess:
        return (
            "不建议作为第二条主线；仅值得做一次 V1.5 口径修复验证",
            "D. A股这条现金牛线在当前口径下弱，叠加 B. 周期/地产等行业污染；不是 C. 与 Quality 高度重复",
        )
    if overlap > 0.5 or corr > 0.9:
        return ("暂不建议作为独立主线", "C. 与 Quality 高度重复")
    return ("值得进入 V1.5", "V1 已呈现一定独立性，但仍需排查 A/B/D")
