# 经营现金流收益率数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 候选最少/中位/最新：37 /
  1919 / 3035。
- 唯一因子值中位数：1919；
  合格月份占比：97.83%。
- Top40 日均成交额中位数：165.8 百万元。
- 与 ROA/E/P/低波/120日收益/对数成交额 Spearman 中位数：
  0.103 / 0.476 /
  0.361 / -0.114 /
  -0.055。
- 最新现金流收益率 P1/中位/P99：0.07% /
  3.94% / 73.09%。
- 复权缺失/重大公司行为占比：
  1.03% /
  8.82%。
- 可见性越界/重复/无效值：0 /
  0 / 0。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_roa
- PASS：distinct_from_earnings_yield
- PASS：distinct_from_price_low_volatility
- PASS：distinct_from_momentum
- PASS：distinct_from_liquidity_level
- FAIL：adjustment_missing_within_limit
- PASS：zero_visibility_violations
- PASS：zero_statement_period_mismatches
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

## 结论

决策：`REJECTED_BEFORE_BACKTEST`。本阶段未读取未来收益或运行回测。
