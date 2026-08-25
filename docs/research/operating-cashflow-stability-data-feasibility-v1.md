# 经营现金流稳定性数据可行性 V1

- 数据截止：20260724，月末截面：138。
- 候选数最少/中位/最新：1134 /
  2137 / 2887。
- 因子唯一值中位数：2137；
  合格月份占比：100.00%。
- Top40 成交额中位数：136,177,558 元。
- 与 ROA稳定性/价格低波/120日收益/对数成交额的秩相关中位数：
  0.355 /
  0.111 /
  0.019 /
  0.018。
- 最新截面 OCF波动 P1/中位/P99：0.58% /
  3.61% / 16.70%；
  五年 OCF/资产中位数：5.48%。
- 重复/公告越界/窗口长度错误：0 /
  0 / 0。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_roa_stability
- PASS：distinct_from_price_low_volatility
- PASS：distinct_from_momentum
- PASS：distinct_from_liquidity_level
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_window_violations
- PASS：zero_invalid_rows

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 本阶段没有读取未来收益、执行回测或调整参数。
