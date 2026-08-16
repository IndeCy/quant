# 点时盈利收益率数据可行性 V1

- 数据截止：20260724，月末截面：138。
- 候选数最少/中位/最新：44 /
  2019 / 2766。
- 因子唯一值中位数：1984；
  合格月份占比：97.83%。
- Top40 成交额中位数：235,552,267 元。
- 与 ROA/价格低波/120日收益/对数成交额的秩相关中位数：
  0.621 / 0.426 /
  -0.154 / -0.032。
- 最新 E/P P1/中位/P99：0.09% /
  2.19% / 17.34%。
- 公司行为复权因子缺失/重大变化剔除：
  4.95% /
  9.95%。
- 公告越界/重复/无效值：0 /
  0 / 0。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_roa
- PASS：distinct_from_price_low_volatility
- PASS：distinct_from_momentum
- PASS：distinct_from_liquidity_level
- FAIL：adjustment_missing_within_limit
- PASS：zero_visibility_violations
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

## 结论

- 决策：`REJECTED_BEFORE_BACKTEST`。
- 本阶段没有读取未来收益、执行回测或调整参数。
