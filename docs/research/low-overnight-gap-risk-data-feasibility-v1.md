# 低隔夜跳空风险数据可行性 V1

- 数据截止：20260724，月末截面：138。
- 候选数最小/中位/最新：1457 /
  2476 / 4030。
- 因子唯一值中位数：2476。
- Top40日均成交额中位数：104,737,632 元。
- 合格月份占比：100.00%。
- 与120日收益/60日收盘波动的秩相关中位数：
  -0.300 / -0.803。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_momentum
- FAIL：distinct_from_close_to_close_low_volatility
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_invalid_rows

## 结论

- 决策：`REJECTED_BEFORE_BACKTEST`。
- 本阶段未读取未来收益、执行回测或调整参数。
