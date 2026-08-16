# 净经营资产数据可行性 V1

- 数据截止：20260724，月末截面：138。
- 候选数最小/中位/最新：1407 /
  2384 / 3933。
- 因子唯一值中位数：2384。
- Top40 成交额中位数：130,665,082 元；
  合格月份占比：100.00%。
- 与120日收益/60日价格波动/对数成交额水平的秩相关中位数：
  0.004 / 0.005 /
  0.049。
- 最新截面 NOA 率 P1/中位/P99：-0.94% /
  54.98% / 86.83%。
- 交易性资产/全部债务分项缺失率：
  51.80% /
  6.62%。
- 公告越界/公式错误/重复：0 /
  0 /
  0。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_momentum
- PASS：distinct_from_low_volatility
- PASS：distinct_from_liquidity_level
- PASS：trading_asset_missing_within_limit
- PASS：debt_components_missing_within_limit
- PASS：zero_visibility_violations
- PASS：zero_formula_identity_violations
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 本阶段没有读取未来收益、执行回测或调整参数。
