# 走步双因子残差动量数据可行性 V1

- 数据截止：20260724，月末截面：
  138。
- 估计窗：信号日前252至121个交易日；评价窗：120至20个交易日。
- 风格因子：沪深300收益、中证500相对沪深300收益。
- 本阶段不读取未来收益、不执行回测、不选择参数。

## 数据与区分度

- 候选数最少/中位/最新：
  837 /
  2472 /
  4022。
- 因子唯一值中位数：
  2472。
- Top40日均成交额中位数：
  512,378,162元。
- 合格月份占比：
  90.6%。
- 与普通12-1动量/60日波动/120日收益秩相关中位数：
  0.588 /
  0.413 /
  0.829。
- 最小估计窗/评价窗观测：
  120 /
  90。
- 最大恒等式误差：
  2.442e-15。

## 冻结门禁

- PASS：qualified_month_share
- PASS：distinct_from_intermediate_momentum
- PASS：distinct_from_low_volatility
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_identity_violations
- PASS：zero_invalid_rows
- PASS：regression_identified

## 结论

- 决策：`CONTINUE_TO_FIXED_MULTIFOLD_BACKTEST`。
- 未通过时禁止进入收益回测；通过只代表允许执行一次固定多折研究。
