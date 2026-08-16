# 长期反转数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 合格月份占比：75.36%。
- 候选数最少/中位/最新：0 /
  2428 / 3994。
- 因子唯一值中位数：2428。
- Top40 日均成交额中位数的月度中位：94.7 百万元。
- 与近期120日收益/60日波动率 Spearman 中位：
  0.089 / 0.044。
- 收益恒等式最大误差：0.000e+00。
- 重复/点时违规/无效值：0 /
  0 / 0。

## 冻结门槛

- FAIL：qualified_month_share
- PASS：distinct_from_recent_momentum
- PASS：distinct_from_low_volatility
- PASS：zero_identity_violations
- PASS：zero_duplicate_rows
- PASS：zero_visibility_violations
- PASS：zero_invalid_rows

## 结论

REJECTED_BEFORE_BACKTEST。本阶段不计算未来收益，也不注册生产策略。
