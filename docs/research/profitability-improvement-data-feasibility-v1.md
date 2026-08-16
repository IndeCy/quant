# 年度 ROA 改善数据可行性 V1

- 数据截止：20260724，月末截面：138。
- ROA 定义：归母净利润除以上年末总资产；因子为连续两年 ROA 之差。
- 只使用信号日前利润表与资产负债表均已披露的1231年报。
- 候选数最少/中位/最新：1398 /
  2365 / 3930。
- 因子唯一值中位数：2365；
  合格月份占比：100.00%。
- Top40 成交额中位数：142,332,946 元。
- 与当前 ROA/价格低波/120日收益/对数成交额的秩相关中位数：
  0.301 / 0.020 /
  0.037 / 0.042。
- 最新 ROA 改善 P1/中位/P99：-11.81% /
  -0.06% / 15.73%。
- 公告越界/重复/无效值：0 /
  0 / 0。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_current_roa
- PASS：distinct_from_price_low_volatility
- PASS：distinct_from_momentum
- PASS：distinct_from_liquidity_level
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_invalid_rows

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 本阶段没有读取未来收益、执行回测或调整参数。
