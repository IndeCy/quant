"""生成游资主线与龙头识别报告。"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from runtime.hot_money_leader import build_leader_stock_daily
from runtime.hot_money_sector import build_sector_momentum_daily


def main(argv: list[str] | None = None) -> int:
    """CLI 入口，仅读本地缓存并输出研究报告。"""
    parser = argparse.ArgumentParser(description="生成游资主线与龙头识别报告")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--sector-map-csv")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    limit_rows = _read_limit_rows(Path(args.db_path))
    sector_map = _read_sector_map(args.sector_map_csv)
    sector = build_sector_momentum_daily(limit_rows, sector_map)
    leader = build_leader_stock_daily(limit_rows, sector, sector_map)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_report(sector, leader), encoding="utf-8")
    return 0


def _read_limit_rows(db_path: Path) -> pd.DataFrame:
    """读取本地涨跌停缓存，不在报告脚本里实时调接口。"""
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute("SELECT * FROM limit_list_daily ORDER BY trade_date, ts_code").fetchdf()


def _read_sector_map(sector_map_csv: str | None) -> pd.DataFrame | None:
    if not sector_map_csv:
        return None
    return pd.read_csv(sector_map_csv)


def _render_report(sector: pd.DataFrame, leader: pd.DataFrame) -> str:
    if sector.empty:
        return "# 游资主线与龙头识别报告\n\n无可用涨停缓存数据。\n"
    latest = str(sector["trade_date"].max())
    lines = ["# 游资主线与龙头识别报告", "", f"- 最新交易日：{latest}", ""]
    lines.extend(_render_sector_table(sector, latest))
    lines.extend(["", "## 龙头候选", ""])
    lines.extend(_render_leader_table(leader, latest))
    lines.append("")
    return "\n".join(lines)


def _render_sector_table(sector: pd.DataFrame, latest: str) -> list[str]:
    latest_sector = sector[sector["trade_date"].astype(str).eq(latest)].sort_values("rank")
    lines = ["## 主线板块", "", "| 排名 | 板块 | 分数 | 是否主线 | 理由 |", "|---|---|---:|---|---|"]
    for _, row in latest_sector.iterrows():
        lines.append(f"| {int(row['rank'])} | {row['sector_name']} | {float(row['sector_score']):.2f} | {bool(row['is_mainline'])} | {row['reason']} |")
    return lines


def _render_leader_table(leader: pd.DataFrame, latest: str) -> list[str]:
    lines = ["| 板块 | 股票 | 角色 | 分数 | 理由 |", "|---|---|---|---:|---|"]
    latest_leader = leader[leader["trade_date"].astype(str).eq(latest)].sort_values(["sector_name", "role", "leader_score"], ascending=[True, True, False])
    for _, row in latest_leader.iterrows():
        lines.append(f"| {row['sector_name']} | {row['name']}({row['ts_code']}) | {row['role']} | {float(row['leader_score']):.2f} | {row['reason']} |")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
