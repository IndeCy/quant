#!/usr/bin/env python3
"""生成游资情绪状态机研究报告，不执行交易。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.tushare_limit_incremental import LimitListDuckDBStore
from runtime.hot_money_emotion import build_market_emotion_daily
from runtime.hot_money_state import MarketStateEngine


def main() -> None:
    """读取本地涨跌停缓存并生成市场状态报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-path", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = LimitListDuckDBStore(Path(args.cache_path)).load(args.start_date, args.end_date)
    emotion = build_market_emotion_daily(rows)
    state = MarketStateEngine().classify_series(emotion)
    report_path = output_dir / "market_state_report.md"
    report_path.write_text(_render_report(state), encoding="utf-8")
    print(str(report_path))


def _render_report(state) -> str:
    if state.empty:
        return "# 游资情绪状态报告\n\n- 市场状态：无数据\n"
    latest = state.iloc[-1]
    rows = "\n".join(
        f"| {row.trade_date} | {row.smoothed_state} | {row.emotion_score:.2f} | {row.risk_score:.2f} | {row.transition_reason} |"
        for row in state.itertuples()
    )
    return f"""# 游资情绪状态报告

- 最新交易日：{latest.trade_date}
- 最新市场状态：{latest.smoothed_state}
- 最新情绪分：{latest.emotion_score:.2f}
- 最新风险分：{latest.risk_score:.2f}

| 日期 | 市场状态 | 情绪分 | 风险分 | 原因 |
|---|---:|---:|---:|---|
{rows}
"""


if __name__ == "__main__":
    main()
