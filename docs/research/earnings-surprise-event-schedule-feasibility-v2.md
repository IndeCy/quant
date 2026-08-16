# SUE 事件驱动调仓日历可行性 V2

- 数据截止：20260724。
- 可重选月份占比：92.03%。
- 最长连续沿用持仓：2个月。
- 首次可重选日期：20150227。
- 完整年度最少重选次数：
  10。

## 完整年度重选次数

- 2015：11次
- 2016：12次
- 2017：12次
- 2018：11次
- 2019：11次
- 2020：11次
- 2021：12次
- 2022：12次
- 2023：10次
- 2024：10次
- 2025：11次

## 固定门槛

- PASS：data_integrity
- PASS：event_month_share_at_least_85pct
- PASS：each_fold_event_share_at_least_80pct
- PASS：at_most_two_consecutive_skipped_months
- PASS：at_least_eight_rebalances_per_full_year
- PASS：first_rebalance_by_20150331

结论：允许按事件调仓定义进入回测。
