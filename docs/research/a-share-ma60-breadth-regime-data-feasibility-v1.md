# 全A MA60 宽度周频状态数据可行性 V1

- 区间：20150101 至 20260615
- 周覆盖：586 / 586（100.00%）
- 有效股票数中位/最少：3718 / 1306
- 宽度 Min/Q10/Median/Q90/Max：1.69% /
  16.32% / 42.23% /
  83.75% / 99.87%

## 冻结门禁

- PASS `weekly_coverage_at_least_99pct`
- PASS `median_universe_at_least_2500`
- FAIL `minimum_universe_at_least_1500`
- PASS `breadth_q90_minus_q10_at_least_20pct`
- PASS `breadth_within_zero_one`

## 结论

`REJECTED_BEFORE_BACKTEST`。本阶段不读取资产后续收益、不回测、不注册策略。
