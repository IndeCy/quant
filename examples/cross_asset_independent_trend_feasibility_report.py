"""五资产独立趋势槽位的数据可行性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染基金覆盖、趋势构造和状态分布门禁。"""
    coverage = "\n".join(
        f"| {item['symbol']} | {item['start_date']} | {item['end_date']} | "
        f"{item['row_count']} |"
        for item in result["coverage"]
    )
    activity = "\n".join(
        f"| {symbol} | {ratio:.2%} |"
        for symbol, ratio in result["active_share"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 五资产独立趋势槽位数据可行性 V1

- 数据截止：{result['latest_common_date']}。
- 风险资产各固定25%槽位；MA60>MA120时启用，否则转5年国债。
- 本阶段不读取未来收益，不进行相对排名或参数搜索。
- 可构造月末：{result['constructible_months']} /
  {result['signal_months']}，重复/无效：{result['duplicate_rows']} /
  {result['invalid_rows']}。
- 共同交易日保留比例：{result['common_calendar_retention']:.2%}。

| 资产 | 起始 | 截止 | 行数 |
|---|---|---|---:|
{coverage}

| 风险资产 | 趋势开启比例 |
|---|---:|
{activity}

## 冻结门禁

{checks}

结论：`{result['decision']}`。未通过时不执行收益回测。
"""
