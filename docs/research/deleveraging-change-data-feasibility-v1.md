# 年度去杠杆变化数据可行性 V1

- 数据截止：20260724，月末截面：138。
- 候选数最少/中位/最新：1402 /
  2376 / 3933。
- 因子唯一值中位数：2376；
  合格月份占比：100.00%。
- Top40 成交额中位数：120,957,788 元。
- 与低负债率/价格低波/120日收益/对数成交额的秩相关中位数：
  0.153 / 0.076 /
  -0.024 / 0.020。
- 最新负债率变化 P1/中位/P99：-21.03% /
  0.63% / 18.93%。
- 公告越界/重复/无效值：0 /
  0 / 0。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_low_leverage
- PASS：distinct_from_price_low_volatility
- PASS：distinct_from_momentum
- PASS：distinct_from_liquidity_level
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_invalid_rows

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 本阶段没有读取未来收益、执行回测或调整参数。
