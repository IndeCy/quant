# 交易活跃度稳定性数据可行性 V1

- 数据截止：20260728，月末截面：138。
- 候选数最小/中位/最新：1457 /
  2476 / 4030。
- 因子唯一值中位数：2476。
- Top40 成交额中位数：118,222,148 元。
- 合格月份占比：100.00%。
- 与120日收益/60日价格波动/对数成交额水平的秩相关中位数：
  -0.182 / -0.490 /
  -0.062。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_momentum
- PASS：distinct_from_low_volatility
- PASS：distinct_from_liquidity_level
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_invalid_rows

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 本阶段没有读取未来收益、执行回测或调整参数。
