# 融资净买入广度月频状态数据可行性 V1

- 区间：20150130 至 20260630
- 月份：138；有效股票数中位：1410
- 广度 Min/Q10/Median/Q90/Max：1.05% /
  20.63% / 44.91% /
  67.06% / 96.39%
- 广度≥50%月份占比：39.86%

## 冻结门禁

- PASS `month_count_at_least_130`
- PASS `nonzero_valid_share_is_100pct`
- PASS `median_valid_count_at_least_500`
- PASS `breadth_q90_minus_q10_at_least_10pct`
- PASS `unique_values_at_least_100`
- PASS `breadth_within_zero_one`

## 结论

`CONTINUE_TO_FIXED_MONTHLY_REGIME_BACKTEST`。本阶段不读取资产收益、不回测、不注册策略。
