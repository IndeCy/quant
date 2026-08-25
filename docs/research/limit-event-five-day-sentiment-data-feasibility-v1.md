# 涨跌停五日情绪周频状态数据可行性 V1

- 区间：20230101 至 20260615
- 周覆盖：177 / 177（100.00%）
- 日涨跌停事件中位数：60
- 情绪 Min/Q10/Median/Q90/Max：-0.377 /
  0.455 / 0.760 /
  0.909 / 1.000

## 冻结门禁

- PASS `weekly_coverage_at_least_99pct`
- PASS `nonzero_event_week_share_at_least_95pct`
- PASS `median_daily_events_at_least_20`
- PASS `sentiment_q90_minus_q10_at_least_30pct`
- PASS `unique_weekly_values_at_least_100`

## 结论

`CONTINUE_TO_FIXED_REGIME_BACKTEST`。本阶段不读取资产后续收益、不回测、不注册策略。
