"""
回测 HTML 报表渲染模块

该模块只负责把已有回测结果转换成静态 HTML，不负责拉取行情或执行策略。
这样报表展示逻辑可以独立测试，也便于后续复用到不同标的和策略。
"""

from __future__ import annotations

from html import escape
from typing import Dict, Iterable, List, Mapping

import pandas as pd


def _format_percent(value: float) -> str:
    """格式化百分比指标。"""
    return f"{value:.2%}"


def _format_number(value: float) -> str:
    """格式化金额或数值，便于业务侧快速扫读。"""
    return f"{value:,.2f}"


def _format_metric(label: str, value: float) -> str:
    """根据指标含义选择合适的展示格式。"""
    if label in {"总收益率", "年化收益率", "最大回撤", "胜率", "波动率", "基线总收益率", "超额收益率", "基线年化收益率", "年化超额收益率"}:
        return _format_percent(float(value))
    if label in {"最终资产"}:
        return f"¥{_format_number(float(value))}"
    if label in {"交易次数"}:
        return str(int(value))
    return f"{float(value):.2f}"


def _build_line_chart(
    points: List[tuple[str, float]],
    title: str,
    stroke: str,
    fill: str = "none",
) -> str:
    """生成简单 SVG 折线图，避免引入前端图表依赖。"""
    width = 920
    height = 260
    pad = 36
    if not points:
        return "<div class=\"empty-chart\">暂无图表数据</div>"

    values = [value for _, value in points]
    min_value = min(values)
    max_value = max(values)
    span = max(max_value - min_value, 1e-9)

    coords = []
    for index, (_, value) in enumerate(points):
        x = pad if len(points) == 1 else pad + index * (width - pad * 2) / (len(points) - 1)
        y = height - pad - (value - min_value) * (height - pad * 2) / span
        coords.append(f"{x:.2f},{y:.2f}")

    y_top = _format_number(max_value)
    y_bottom = _format_number(min_value)
    first_date = escape(points[0][0])
    last_date = escape(points[-1][0])

    return f"""
    <section class="chart-panel">
      <div class="panel-title">{escape(title)}</div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
        <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" class="axis" />
        <line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" class="axis" />
        <text x="{pad}" y="22" class="axis-label">{y_top}</text>
        <text x="{pad}" y="{height - 8}" class="axis-label">{y_bottom}</text>
        <text x="{pad}" y="{height - 12}" class="date-label">{first_date}</text>
        <text x="{width - pad - 96}" y="{height - 12}" class="date-label">{last_date}</text>
        <polyline points="{' '.join(coords)}" fill="{fill}" stroke="{stroke}" stroke-width="3" />
      </svg>
    </section>
    """


def _build_metric_cards(summary: Mapping[str, float]) -> str:
    """生成核心指标卡片。"""
    preferred = [
        "总收益率",
        "基线总收益率",
        "超额收益率",
        "年化收益率",
        "基线年化收益率",
        "年化超额收益率",
        "夏普比率",
        "最大回撤",
        "波动率",
        "胜率",
        "交易次数",
        "最终资产",
    ]
    cards = []
    for label in preferred:
        if label not in summary:
            continue
        value = _format_metric(label, float(summary[label]))
        cards.append(
            f"""
            <article class="metric-card">
              <div class="metric-label">{escape(label)}</div>
              <div class="metric-value">{escape(value)}</div>
            </article>
            """
        )
    return "\n".join(cards)


def _build_trade_rows(trades: Iterable[Mapping[str, object]]) -> str:
    """生成交易明细表格行。"""
    rows = []
    for trade in trades:
        quantity = int(trade.get("quantity", 0))
        action = "买入" if quantity > 0 else "卖出"
        date_value = pd.to_datetime(trade.get("date")).strftime("%Y-%m-%d")
        rows.append(
            f"""
            <tr>
              <td>{escape(date_value)}</td>
              <td>{escape(str(trade.get("symbol", "")))}</td>
              <td><span class="badge {'buy' if quantity > 0 else 'sell'}">{action}</span></td>
              <td>{abs(quantity)}</td>
              <td>{_format_number(float(trade.get("price", 0.0)))}</td>
              <td>{_format_number(float(trade.get("commission", 0.0)))}</td>
            </tr>
            """
        )
    if not rows:
        return "<tr><td colspan=\"6\" class=\"empty-cell\">本次回测未触发交易信号</td></tr>"
    return "\n".join(rows)


def _build_recent_rows(daily_values: pd.DataFrame) -> str:
    """生成最近资产表格行。"""
    rows = []
    for index, row in daily_values.tail(8).iterrows():
        rows.append(
            f"""
            <tr>
              <td>{escape(pd.to_datetime(index).strftime("%Y-%m-%d"))}</td>
              <td>¥{_format_number(float(row['total_value']))}</td>
              <td>¥{_format_number(float(row['cash']))}</td>
              <td>¥{_format_number(float(row['positions_value']))}</td>
              <td>{_format_percent(float(row.get('returns', 0.0)))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def _drawdown_points(daily_values: pd.DataFrame) -> List[tuple[str, float]]:
    """计算回撤序列，用于报表曲线展示。"""
    total_value = daily_values["total_value"]
    running_max = total_value.expanding().max()
    drawdown = (total_value - running_max) / running_max
    return [(pd.to_datetime(index).strftime("%Y-%m-%d"), float(value)) for index, value in drawdown.items()]


def build_backtest_report_html(
    title: str,
    subtitle: str,
    summary: Dict[str, float],
    daily_values: pd.DataFrame,
    trades: Iterable[Mapping[str, object]],
) -> str:
    """构建完整静态 HTML 回测报表。"""
    equity_points = [
        (pd.to_datetime(index).strftime("%Y-%m-%d"), float(row["total_value"]))
        for index, row in daily_values.iterrows()
    ]
    drawdown_points = _drawdown_points(daily_values)

    metric_cards = _build_metric_cards(summary)
    equity_chart = _build_line_chart(equity_points, "资金曲线", "#2563eb")
    drawdown_chart = _build_line_chart(drawdown_points, "回撤曲线", "#dc2626")
    trade_rows = _build_trade_rows(trades)
    recent_rows = _build_recent_rows(daily_values)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172033; background: #f5f7fb; }}
    header {{ background: #ffffff; border-bottom: 1px solid #e3e8f2; padding: 28px 40px 22px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; font-weight: 700; letter-spacing: 0; }}
    .subtitle {{ margin: 0; color: #5f6b7a; font-size: 14px; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px 24px 48px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .metric-card, .chart-panel, .table-panel {{ background: #ffffff; border: 1px solid #e3e8f2; border-radius: 8px; }}
    .metric-card {{ padding: 18px; min-height: 92px; }}
    .metric-label {{ color: #667085; font-size: 13px; margin-bottom: 8px; }}
    .metric-value {{ color: #101828; font-size: 24px; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 18px; }}
    .panel-title {{ padding: 16px 18px 0; font-weight: 700; color: #253044; }}
    svg {{ width: 100%; height: auto; display: block; padding: 8px 12px 14px; }}
    .axis {{ stroke: #d7deea; stroke-width: 1; }}
    .axis-label, .date-label {{ fill: #667085; font-size: 12px; }}
    .table-panel {{ overflow: hidden; }}
    .table-title {{ padding: 16px 18px; font-weight: 700; border-bottom: 1px solid #e3e8f2; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid #edf1f7; text-align: left; white-space: nowrap; }}
    th {{ color: #667085; background: #f8fafc; font-weight: 600; }}
    .badge {{ display: inline-block; min-width: 42px; text-align: center; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .badge.buy {{ color: #166534; background: #dcfce7; }}
    .badge.sell {{ color: #991b1b; background: #fee2e2; }}
    .empty-cell {{ color: #667085; text-align: center; padding: 28px; }}
    .empty-chart {{ padding: 32px; color: #667085; }}
    @media (max-width: 900px) {{ .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} header {{ padding: 22px; }} main {{ padding: 18px; }} }}
    @media (max-width: 560px) {{ .metrics {{ grid-template-columns: 1fr; }} h1 {{ font-size: 22px; }} th, td {{ padding: 10px; font-size: 12px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <p class="subtitle">{escape(subtitle)}</p>
  </header>
  <main>
    <section class="metrics">
      {metric_cards}
    </section>
    <section class="grid">
      {equity_chart}
      {drawdown_chart}
      <section class="table-panel">
        <div class="table-title">交易明细</div>
        <table>
          <thead>
            <tr><th>日期</th><th>标的</th><th>方向</th><th>数量</th><th>成交价</th><th>费用</th></tr>
          </thead>
          <tbody>{trade_rows}</tbody>
        </table>
      </section>
      <section class="table-panel">
        <div class="table-title">最近资产快照</div>
        <table>
          <thead>
            <tr><th>日期</th><th>总资产</th><th>现金</th><th>持仓市值</th><th>日收益</th></tr>
          </thead>
          <tbody>{recent_rows}</tbody>
        </table>
      </section>
    </section>
  </main>
</body>
</html>
"""
