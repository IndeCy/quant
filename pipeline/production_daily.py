"""Production Candidate Daily Pipeline 产物与门禁。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.quality_overlay_paper import QualityPaperSnapshot
from data.calendar import TradingCalendar


def validate_pipeline_ready(trade_date: str, benchmark_curve: pd.Series) -> None:
    """策略日期、基准和复权数据必须一致后才允许出正式日报。"""
    if benchmark_curve.empty:
        raise RuntimeError("基准未更新: 510300复权基准为空")
    latest = pd.Timestamp(benchmark_curve.index.max()).strftime("%Y%m%d")
    if latest < trade_date:
        raise RuntimeError(f"基准未更新: 策略日期{trade_date}, 基准日期{latest}")


def write_daily_artifacts(
    output_root: str | Path,
    snapshot: QualityPaperSnapshot,
    holdings: pd.DataFrame,
    run: Any,
    benchmark_curve: pd.Series,
    previous_snapshot: QualityPaperSnapshot | None = None,
) -> Path:
    """写出每日固定产物到 runs/YYYYMMDD。"""
    validate_pipeline_ready(snapshot.trade_date, benchmark_curve)
    run_dir = Path(output_root) / snapshot.trade_date
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics = build_strategy_metrics(snapshot, run, benchmark_curve)
    rebalance_plan = build_rebalance_plan(snapshot, holdings, previous_snapshot)
    portfolio_snapshot = build_portfolio_snapshot(snapshot, holdings)

    (run_dir / "strategy_metrics.json").write_text(
        json.dumps(_json_ready(metrics), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rebalance_plan.to_csv(run_dir / "rebalance_plan.csv", index=False)
    portfolio_snapshot.to_csv(run_dir / "portfolio_snapshot.csv", index=False)
    (run_dir / "daily_report.md").write_text(
        render_daily_report(snapshot, metrics, rebalance_plan),
        encoding="utf-8",
    )
    write_run_log(run_dir, "SUCCESS", "daily pipeline completed")
    return run_dir


def build_strategy_metrics(snapshot: QualityPaperSnapshot, run: Any, benchmark_curve: pd.Series) -> dict[str, Any]:
    """汇总日报关键指标。"""
    values = pd.Series(run.result.daily_values).dropna().astype(float).sort_index()
    date = pd.Timestamp(snapshot.trade_date)
    if date not in values.index:
        date = values.index.max()
    nav = values / float(values.iloc[0])
    returns = nav.pct_change().fillna(0.0)
    benchmark = benchmark_curve.reindex(nav.index).ffill().dropna()
    benchmark_nav = benchmark / float(benchmark.iloc[0])
    latest_nav = float(nav.loc[date])
    latest_benchmark = float(benchmark_nav.loc[:date].iloc[-1])
    month_start = nav.loc[nav.index.strftime("%Y%m") == snapshot.trade_date[:6]].iloc[0]
    year_start = nav.loc[nav.index.strftime("%Y") == snapshot.trade_date[:4]].iloc[0]
    drawdown = nav / nav.cummax() - 1.0
    return {
        "trade_date": snapshot.trade_date,
        "selection_date": snapshot.selection_date,
        "portfolio_nav": latest_nav,
        "benchmark_nav": latest_benchmark,
        "daily_return": float(returns.loc[date]),
        "month_return": float(latest_nav / month_start - 1),
        "ytd_return": float(latest_nav / year_start - 1),
        "excess_return": float(latest_nav - latest_benchmark),
        "current_drawdown": float(drawdown.loc[date]),
        "volatility20": float(snapshot.volatility20),
        "risk_state": snapshot.risk_state,
        "target_exposure": float(snapshot.exposure),
        "total_execution_cost": float(run.result.total_cost),
        "failed_order_count": len(run.result.failed_orders),
        "turnover_notional": float(run.result.turnover_notional),
    }


def build_rebalance_plan(
    snapshot: QualityPaperSnapshot,
    holdings: pd.DataFrame,
    previous_snapshot: QualityPaperSnapshot | None = None,
) -> pd.DataFrame:
    """根据目标权重和上一日目标权重生成调仓建议。"""
    previous = previous_snapshot.target_weights if previous_snapshot is not None else {}
    rows: list[dict[str, Any]] = []
    all_symbols = sorted(set(previous) | set(snapshot.target_weights))
    name_map = {}
    if not holdings.empty and {"symbol", "name"} <= set(holdings.columns):
        name_map = dict(zip(holdings["symbol"], holdings["name"]))
    for symbol in all_symbols:
        old = float(previous.get(symbol, 0.0))
        new = float(snapshot.target_weights.get(symbol, 0.0))
        delta = new - old
        rows.append(
            {
                "trade_date": snapshot.trade_date,
                "symbol": symbol,
                "name": name_map.get(symbol, ""),
                "previous_weight": old,
                "target_weight": new,
                "weight_delta": delta,
                "action": _action_from_delta(delta, old, new),
                "reason": _rebalance_reason(snapshot, old, new),
            }
        )
    return pd.DataFrame(rows)


def build_portfolio_snapshot(snapshot: QualityPaperSnapshot, holdings: pd.DataFrame) -> pd.DataFrame:
    """输出目标组合快照。"""
    frame = holdings.copy()
    if "target_weight" not in frame.columns:
        frame["target_weight"] = frame["symbol"].map(snapshot.target_weights)
    frame.insert(0, "trade_date", snapshot.trade_date)
    frame["risk_state"] = snapshot.risk_state
    frame["target_exposure"] = snapshot.exposure
    return frame


def render_daily_report(
    snapshot: QualityPaperSnapshot,
    metrics: dict[str, Any],
    rebalance_plan: pd.DataFrame,
) -> str:
    """生成每日 Markdown 报告。"""
    action_rows = rebalance_plan[rebalance_plan["action"].ne("HOLD")]
    action_text = "无" if action_rows.empty else _to_markdown_table(action_rows)
    warnings = "\n".join(f"- {item}" for item in snapshot.warnings) or "- 无"
    return f"""# Production Candidate Daily Report

- 交易日：{snapshot.trade_date}
- 策略：Quality Alpha V1 + Volatility Overlay
- 组合净值：{metrics['portfolio_nav']:.4f}
- 510300基准净值：{metrics['benchmark_nav']:.4f}
- 当日收益：{metrics['daily_return']:.2%}
- 本月收益：{metrics['month_return']:.2%}
- 年内收益：{metrics['ytd_return']:.2%}
- 超额收益：{metrics['excess_return']:.2%}
- 当前回撤：{metrics['current_drawdown']:.2%}
- 20日组合波动率：{metrics['volatility20']:.2%}
- 风险层状态：{metrics['risk_state']}
- 当前目标仓位：{metrics['target_exposure']:.2%}

## 调仓建议

{action_text}

## 数据与执行告警

{warnings}
"""


def write_run_log(run_dir: str | Path, status: str, message: str) -> Path:
    """写入运行日志，失败和成功都可审计。"""
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    log_path = path / "run_log.txt"
    log_path.write_text(
        f"{datetime.now().isoformat(timespec='seconds')} [{status}] {message}\n",
        encoding="utf-8",
    )
    return log_path


def build_monthly_review(output_root: str | Path, month: str, strategy_rows: pd.DataFrame) -> Path:
    """生成轻量月度复盘文件。"""
    month_dir = Path(output_root) / month
    month_dir.mkdir(parents=True, exist_ok=True)
    frame = strategy_rows[strategy_rows["trade_date"].astype(str).str.startswith(month)].copy()
    if frame.empty:
        text = f"# Monthly Review {month}\n\n本月无策略观测数据。\n"
    else:
        start = frame.iloc[0]
        end = frame.iloc[-1]
        month_return = float(end["nav"] / start["nav"] - 1)
        benchmark_return = float(end["benchmark_nav"] / start["benchmark_nav"] - 1)
        trigger_count = int((frame["exposure"].astype(float) < 1.0).sum())
        text = f"""# Monthly Review {month}

- 本月收益：{month_return:.2%}
- 本月超额：{month_return - benchmark_return:.2%}
- 本月最低回撤：{float(frame['drawdown'].min()):.2%}
- 风险层触发次数：{trigger_count}
- 持仓变化：见当月 daily_report 与 rebalance_plan.csv
- 行业暴露变化：当前数据源行业覆盖不足，待补齐后接入
"""
    path = month_dir / "monthly_review.md"
    path.write_text(text, encoding="utf-8")
    return path


def is_month_end_trade_date(trade_date: str, calendar: TradingCalendar | None = None) -> bool:
    """使用真实交易日历判断是否为当月最后一个交易日。"""
    current = pd.Timestamp(trade_date)
    month_end = current + pd.offsets.MonthEnd(0)
    trade_calendar = calendar or TradingCalendar()
    days = trade_calendar.trading_days(current.replace(day=1), month_end)
    return bool(days and days[-1].strftime("%Y%m%d") == trade_date)


def _action_from_delta(delta: float, old: float, new: float) -> str:
    if abs(delta) < 1e-10:
        return "HOLD"
    if old <= 0 and new > 0:
        return "BUY_NEW"
    if new <= 0 and old > 0:
        return "SELL_OUT"
    return "BUY_UP" if delta > 0 else "SELL_DOWN"


def _rebalance_reason(snapshot: QualityPaperSnapshot, old: float, new: float) -> str:
    if snapshot.risk_state == "REDUCED":
        return "risk_overlay_reduce_exposure"
    if old == 0 and new > 0:
        return "monthly_quality_selection_enter"
    if old > 0 and new == 0:
        return "monthly_quality_selection_exit"
    if old != new:
        return "target_weight_changed"
    return "no_change"


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if hasattr(value, "item"):
        return value.item()
    return value


def _to_markdown_table(frame: pd.DataFrame) -> str:
    """不依赖 tabulate 的轻量 Markdown 表格。"""
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in frame.iterrows():
        values = [str(row[column]) for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
