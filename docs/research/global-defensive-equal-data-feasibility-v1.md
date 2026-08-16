# 全球防守三资产等权数据可行性 V1

- 数据截止：20260724。
- 固定资产：标普500ETF、黄金ETF、5年国债ETF，各三分之一。
- 本阶段只检查统一qfq、覆盖、共同交易日和成交额，不读取组合收益。
- 可构造月末：138 /
  138，
  共同交易日保留率：99.67%。
- 数据滞后：0个自然日；
  重复/无效/异常跳变：0 /
  0 / 0。

| 资产 | 代码 | 起始 | 截止 | 行数 |
|---|---|---|---|---:|
| 标普500ETF | 513500.SH | 20140115 | 20260724 | 3043 |
| 黄金ETF | 518880.SH | 20140102 | 20260724 | 3053 |
| 5年国债ETF | 511010.SH | 20140102 | 20260724 | 3053 |

| 资产 | 月末成交额中位数(元) | 月末成交额最小值(元) |
|---|---:|---:|
| 标普500ETF | 84,796,558 | 261,321 |
| 黄金ETF | 939,815,815 | 9,309,255 |
| 5年国债ETF | 230,822,026 | 15,263,550 |

## 冻结门禁

- PASS：all_assets_history_starts_before_2015
- PASS：all_assets_latest_same_date
- PASS：data_is_fresh
- PASS：common_calendar_retention
- PASS：monthly_portfolio_constructible
- PASS：all_assets_liquid
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows
- PASS：zero_adjusted_price_jump_violations

结论：`CONTINUE_TO_FIXED_MULTIFOLD_BACKTEST`。未通过时禁止收益回测。
