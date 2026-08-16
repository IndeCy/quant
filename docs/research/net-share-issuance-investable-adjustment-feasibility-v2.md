# 净股本发行可投复权覆盖可行性 V2

- 修正：复权覆盖率只在标准可投股票池内计算；其余口径和门槛不变。
- 数据截止：20260724，月末截面 126 个。
- 总候选最少/中位/最新：11 /
  2342 / 3885。
- 缩股候选最少/中位/最新：1 /
  320 / 637。
- 全样本/2022年后可组成无并列Top40月份：
  92.86% /
  100.00%。
- 最新变化 P1/中位/P99：-2.58% /
  0.00% / 27.22%；
  零变化占比 60.67%。
- 可投池复权缺失/公司行为歧义：
  6.97% /
  10.89%。

## 冻结门槛

- PASS：candidate_month_share
- PASS：distinguishable_month_share
- PASS：locked_distinguishable_month_share
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows
- FAIL：adjustment_coverage_at_least_95pct

## 结论

REJECTED_BEFORE_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
