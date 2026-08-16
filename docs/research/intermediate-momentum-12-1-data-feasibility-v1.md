# 12-1月中期动量数据可行性 V1

- 数据截止：20260724，月末截面：138。
- 候选数最小/中位/最新：1244 /
  2476 / 4030。
- 因子唯一值中位数：2476。
- Top40 日均成交额中位数：564,492,873 元。
- 合格月份占比：100.00%。
- 与120日收益/60日价格波动秩相关中位数：
  0.546 / 0.335。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_existing_120d_momentum
- PASS：distinct_from_low_volatility
- PASS：zero_identity_violations
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_invalid_rows

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 本阶段未读取未来收益、执行回测或调整参数。
