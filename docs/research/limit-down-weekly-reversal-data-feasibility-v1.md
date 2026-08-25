# 跌停流动性释放周频反转数据可行性 V1

- 区间：20230101 至 20260615
- 周信号数：177
- 非空周占比：98.87%
- 候选数中位/最少：28 / 0
- 至少20只候选周占比：69.49%
- 唯一股票：3447
- 次周开盘覆盖：99.68%
- Top10股票事件占比：1.33%

## 冻结门禁

- PASS `nonempty_week_share_at_least_85pct`
- PASS `median_candidates_at_least_20`
- PASS `weeks_with_top20_at_least_60pct`
- PASS `unique_symbols_at_least_800`
- PASS `next_open_coverage_at_least_98pct`
- PASS `top10_symbol_share_at_most_5pct`

## 结论

`CONTINUE_TO_FIXED_WEEKLY_BACKTEST`。本阶段未读取后续收益、未回测、未注册策略。
