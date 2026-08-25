"""Dashboard 数据与静态页面生成。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from monitoring.repository import MonitoringRepository


def build_dashboard_payload(
    repository: MonitoringRepository,
    strategy_id: str = "quality_overlay",
    benchmark_id: str = "510300",
    benchmark_ids: list[str] | None = None,
) -> dict[str, Any]:
    """从监控库导出前端折线图需要的结构化数据。"""
    ids = benchmark_ids or [benchmark_id]
    strategy = repository.load_strategy_history(strategy_id)
    market = repository.load_market_history(ids[0])
    summary = _build_action_summary(strategy)
    market_summary = dict(market.iloc[-1]) if not market.empty else {}
    market_series_by_id = {}
    market_summaries = {}
    for item in ids:
        history = repository.load_market_history(item)
        market_series_by_id[item] = _json_ready(history.to_dict(orient="records"))
        market_summaries[item] = _json_ready(dict(history.iloc[-1]) if not history.empty else {})
    return {
        "summary": _json_ready(summary),
        "market_summary": _json_ready(market_summary),
        "market_summaries": market_summaries,
        "strategy_series": _json_ready(strategy.to_dict(orient="records")),
        "market_series": _json_ready(market.to_dict(orient="records")),
        "market_series_by_id": market_series_by_id,
    }


def write_dashboard_files(payload: dict[str, Any], json_path: str | Path, html_path: str | Path) -> None:
    """写出 Dashboard JSON 和可直接打开的 HTML 页面。"""
    json_file = Path(json_path)
    html_file = Path(html_path)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_file.write_text(_render_html(json.dumps(payload, ensure_ascii=False)), encoding="utf-8")


def _json_ready(value: Any) -> Any:
    """把 pandas/numpy 标量转换成 JSON 友好类型。"""
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if hasattr(value, "item"):
        return value.item()
    return value


def _build_action_summary(strategy) -> dict[str, Any]:
    """把最新指标转成可直接阅读的操作状态。"""
    if strategy.empty:
        return {}
    latest = dict(strategy.iloc[-1])
    previous = dict(strategy.iloc[-2]) if len(strategy) >= 2 else {}
    volatility = float(latest.get("volatility_20") or 0.0)
    exposure = float(latest.get("exposure") or 0.0)
    previous_exposure = float(previous.get("exposure", exposure) or exposure)
    failed = int(latest.get("failed_order_count") or 0)
    previous_failed = int(previous.get("failed_order_count", failed) or 0)

    latest["risk_light"], latest["risk_light_label"] = _risk_light(volatility)
    action_state, action_reason = _action_state(
        volatility=volatility,
        exposure=exposure,
        previous_exposure=previous_exposure,
        failed_order_count=failed,
        previous_failed_order_count=previous_failed,
    )
    latest["action_state"] = action_state
    latest["action_reason"] = action_reason
    return latest


def _risk_light(volatility: float) -> tuple[str, str]:
    """按主策略风控阈值给出预警灯。"""
    if volatility >= 0.45:
        return "RED", "红色"
    if volatility >= 0.35:
        return "YELLOW", "黄色"
    return "GREEN", "绿色"


def _action_state(
    volatility: float,
    exposure: float,
    previous_exposure: float,
    failed_order_count: int,
    previous_failed_order_count: int,
) -> tuple[str, str]:
    """从仓位变化、风险阈值和执行失败推导操作状态。"""
    if failed_order_count > previous_failed_order_count:
        return "执行异常复查", f"失败委托从{previous_failed_order_count}增加到{failed_order_count}，需检查涨跌停、停牌或缺价"
    if exposure < previous_exposure:
        return "风险降仓", f"仓位从{previous_exposure:.2%}降到{exposure:.2%}，按风险层执行降仓预案"
    if exposure > previous_exposure:
        return "风险恢复", f"仓位从{previous_exposure:.2%}恢复到{exposure:.2%}，按风险层恢复目标仓位"
    if volatility >= 0.45 and exposure < 1.0:
        return "维持低仓", f"20日波动率{volatility:.2%}仍高于45%，继续维持防守仓位"
    if volatility >= 0.45:
        return "风险降仓", f"20日波动率{volatility:.2%}超过45%，需要降仓到风险层目标"
    if volatility >= 0.35:
        return "风险观察", f"20日波动率{volatility:.2%}进入35%-45%观察区，暂不触发交易"
    return "不操作", f"20日波动率{volatility:.2%}低于35%，仓位未变化"


def _render_html(payload_json: str) -> str:
    """生成自包含的 ECharts 报表页面。"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Quality Strategy Monitor</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f8fa; color: #172033; }}
    header {{ padding: 18px 24px; background: #111827; color: white; }}
    h1 {{ margin: 0; font-size: 22px; font-weight: 700; }}
    main {{ padding: 18px 24px 28px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .metric {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; }}
    .metric span {{ display: block; color: #6b7280; font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    .panel {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 16px; }}
    .chart {{ width: 100%; height: 360px; }}
    @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 560px) {{ .grid {{ grid-template-columns: 1fr; }} main {{ padding: 12px; }} }}
  </style>
</head>
<body>
  <header><h1>Quality Strategy Monitor</h1></header>
  <main>
    <section class="grid" id="metrics"></section>
    <section class="panel"><div id="navChart" class="chart"></div></section>
    <section class="panel"><div id="riskChart" class="chart"></div></section>
    <section class="panel"><div id="marketChart" class="chart"></div></section>
  </main>
  <script>
    const payload = {payload_json};
    const pct = v => `${{((Number(v || 0)) * 100).toFixed(2)}}%`;
    const num = v => Number(v || 0).toFixed(3);
    const s = payload.summary || {{}};
    const m = payload.market_summary || {{}};
    const cards = [
      ["操作状态", s.action_state || "-"],
      ["风险预警灯", s.risk_light_label || "-"],
      ["数据日期", s.trade_date || "-"],
      ["累计收益", pct(s.cumulative_return)],
      ["超额收益", pct(s.excess_return)],
      ["当前回撤", pct(s.drawdown)],
      ["最大回撤", pct(s.max_drawdown)],
      ["20日波动率", pct(s.volatility_20)],
      ["滚动夏普", num(s.sharpe_rolling)],
      ["当前仓位", pct(s.exposure)],
      ["执行成本", num(s.total_execution_cost)],
      ["失败委托", String(s.failed_order_count || 0)],
      ["大盘日期", m.trade_date || "-"],
      ["大盘状态", m.trend_state || "-"],
      ["大盘回撤", pct(m.benchmark_drawdown)]
    ];
    document.getElementById("metrics").innerHTML = cards.map(([k, v]) => `<div class="metric"><span>${{k}}</span><strong>${{v}}</strong></div>`).join("");
    const strategy = payload.strategy_series || [];
    const marketMap = payload.market_series_by_id || {{"510300": payload.market_series || []}};
    const market = marketMap["510300"] || payload.market_series || [];
    const shanghai = marketMap["000001.SH"] || [];
    const dates = strategy.map(x => x.trade_date);
    const optionBase = title => ({{ title: {{ text: title, left: 8, top: 4 }}, tooltip: {{ trigger: "axis" }}, legend: {{ top: 8, right: 12 }}, grid: {{ left: 52, right: 24, top: 54, bottom: 36 }}, xAxis: {{ type: "category", data: dates }}, yAxis: {{ type: "value" }} }});
    echarts.init(document.getElementById("navChart")).setOption({{ ...optionBase("收益率观测"), series: [
      {{ name: "策略净值", type: "line", showSymbol: false, data: strategy.map(x => x.nav) }},
      {{ name: "510300基准", type: "line", showSymbol: false, data: strategy.map(x => x.benchmark_nav) }},
      {{ name: "超额收益", type: "line", showSymbol: false, data: strategy.map(x => x.excess_return) }}
    ] }});
    echarts.init(document.getElementById("riskChart")).setOption({{ ...optionBase("风险观测"), series: [
      {{ name: "当前回撤", type: "line", showSymbol: false, data: strategy.map(x => x.drawdown) }},
      {{ name: "20日波动率", type: "line", showSymbol: false, data: strategy.map(x => x.volatility_20) }},
      {{ name: "仓位", type: "line", showSymbol: false, data: strategy.map(x => x.exposure) }}
    ] }});
    echarts.init(document.getElementById("marketChart")).setOption({{ ...optionBase("大盘模块"), xAxis: {{ type: "category", data: market.map(x => x.trade_date) }}, series: [
      {{ name: "510300净值", type: "line", showSymbol: false, data: market.map(x => x.benchmark_nav) }},
      {{ name: "上证指数", type: "line", showSymbol: false, data: shanghai.map(x => x.benchmark_nav) }},
      {{ name: "MA60", type: "line", showSymbol: false, data: market.map(x => x.ma60) }},
      {{ name: "MA120", type: "line", showSymbol: false, data: market.map(x => x.ma120) }}
    ] }});
  </script>
</body>
</html>
"""
