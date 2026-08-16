"""全球防守三资产等权组合的数据可行性报告。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ASSET_NAMES = {
    "513500.SH": "标普500ETF",
    "518880.SH": "黄金ETF",
    "511010.SH": "5年国债ETF",
}


def render_report(result: Mapping[str, Any]) -> str:
    """渲染覆盖、流动性和统一复权门禁。"""
    coverage = "\n".join(
        f"| {ASSET_NAMES.get(str(item['symbol']), item['symbol'])} | "
        f"{item['symbol']} | {item['start_date']} | "
        f"{item['end_date']} | {item['row_count']} |"
        for item in result["coverage"]
    )
    liquidity = "\n".join(
        f"| {ASSET_NAMES.get(symbol, symbol)} | "
        f"{values['median_month_end_amount_rmb']:,.0f} | "
        f"{values['minimum_month_end_amount_rmb']:,.0f} |"
        for symbol, values in result["liquidity"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 全球防守三资产等权数据可行性 V1

- 数据截止：{result["latest_common_date"]}。
- 固定资产：标普500ETF、黄金ETF、5年国债ETF，各三分之一。
- 本阶段只检查统一qfq、覆盖、共同交易日和成交额，不读取组合收益。
- 可构造月末：{result["constructible_months"]} /
  {result["signal_months"]}，
  共同交易日保留率：{result["common_calendar_retention"]:.2%}。
- 数据滞后：{result["staleness_days"]}个自然日；
  重复/无效/异常跳变：{result["duplicate_rows"]} /
  {result["invalid_rows"]} / {result["jump_violations"]}。

| 资产 | 代码 | 起始 | 截止 | 行数 |
|---|---|---|---|---:|
{coverage}

| 资产 | 月末成交额中位数(元) | 月末成交额最小值(元) |
|---|---:|---:|
{liquidity}

## 冻结门禁

{checks}

结论：`{result["decision"]}`。未通过时禁止收益回测。
"""
