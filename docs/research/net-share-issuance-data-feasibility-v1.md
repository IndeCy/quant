# 净股本发行数据可行性 V1

- 数据截止：20260724，月末截面 126 个。
- 总候选最少/中位/最新：11 /
  2342 / 3885。
- 缩股候选最少/中位/最新：1 /
  320 / 637。
- 全样本/2022年后可组成无并列Top40的月份：
  92.86% /
  100.00%。
- 最新变化 P1/中位/P99：-2.58% /
  0.00% / 27.22%；
  零变化占比 60.67%。
- 复权缺失/公司行为歧义占比：
  19.89% /
  10.27%。
- 公告越界/重复：0 /
  0。

## 冻结门槛

- PASS：candidate_month_share
- PASS：distinguishable_month_share
- PASS：locked_distinguishable_month_share
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows
- FAIL：adjustment_coverage_at_least_95pct

## 结论

REJECTED_BEFORE_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
