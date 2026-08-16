"""黄金国债等权防守策略鲁棒性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染成本、频率、滚动窗口、相关性与回撤归因。"""
    full_rows = "\n".join(
        f"| {strategy_id} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['annual_turnover']:.2f}x |"
        for strategy_id, item in result["full_metrics"].items()
    )
    rolling_rows = "\n".join(
        f"| {window} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for window, item in result["rolling_metrics"].items()
    )
    correlation_rows = "\n".join(
        f"| {period} | {value:.3f} |"
        for period, value in result["quality_correlations"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    drawdown = result["drawdown_attribution"]
    return f"""# 黄金国债等权防守策略鲁棒性 V1

- 数据截止：{result['latest_date']}。
- 主策略始终固定为黄金50%+5年国债50%，月频恢复等权。
- 10/20bps与季度再平衡只做压力测试，不用于反向选择参数。
- 黄金与国债日收益相关性：{result['asset_return_correlation']:.3f}。
- 正收益滚动三年窗口：
  {result['rolling_positive_share']:.1%}。

| 场景 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
{full_rows}

## 滚动三年

| 窗口 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{rolling_rows}

## 与 Quality 相关性

| 区间 | 日收益相关性 |
|---|---:|
{correlation_rows}

## 最大回撤归因

- 组合峰值/谷底：{drawdown['peak_date']} / {drawdown['trough_date']}。
- 组合区间跌幅：{drawdown['portfolio_return']:.2%}。
- 黄金同期：{drawdown['gold_return']:.2%}。
- 国债同期：{drawdown['bond_return']:.2%}。

## 固定门槛

{checks}

结论：{'具备进入长期前瞻Paper条件' if result['gate']['passed'] else '鲁棒性不足，暂不进入Paper'}。
"""
