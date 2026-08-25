# 涨停首板事件数据可行性 V1

- 研究区间：20230101 至 20260728。
- 本阶段只审计事件覆盖、字段质量、次日行情和样本集中度，不查看事件后收益。
- 交易日覆盖：863/863（100.00%）。
- 全部涨停榜事件 / 涨停事件：86714 / 52062。
- 首板代理 / 剔除ST退市后：28029 / 27990。
- 唯一股票 / 覆盖月份：4316 / 43。
- 次日行情覆盖 / 次日正开盘价：99.67% / 99.67%。
- 前10大高频股票占比：1.29%。

## 冻结门槛

- PASS：trade_date_coverage_at_least_97pct
- PASS：limit_up_events_at_least_30000
- PASS：first_board_events_at_least_5000
- PASS：eligible_events_at_least_4500
- PASS：unique_symbols_at_least_1500
- PASS：covered_months_at_least_42
- PASS：positive_amount_share_at_least_99pct
- PASS：nonnegative_fd_amount_share_at_least_99pct
- PASS：next_day_bar_coverage_at_least_98pct
- PASS：next_day_positive_open_share_at_least_98pct
- PASS：top10_symbol_share_at_most_5pct

结论：允许冻结一次首板次日事件策略定义。
