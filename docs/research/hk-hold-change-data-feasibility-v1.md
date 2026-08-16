# 北向持仓占比增加数据可行性 V1

- 数据截止：20260724，预期月末 113 个。
- 合格月份（全样本/2024年至今）：61.95% /
  16.67%。
- 正向候选最少/中位/最新：0 /
  573 / 0。
- 因子唯一值中位数：250。
- A股北向非空快照覆盖/最少行数/最新行数：
  84.21% /
  1574 /
  3115。
- 2024-08-19 披露变化后，A股北向非空月占比：
  34.78%。
- 最新正向变化 P1/中位/P99：0.0100 /
  0.1500 / 1.3408 个百分点。
- 因子与成交额/波动率/120日收益的月度 Spearman 中位：
  0.228 / 0.174 /
  0.221。
- 公告越界/重复/比例越界/月间隔异常：
  0 /
  0 /
  0 /
  0。

## 冻结门槛

- FAIL：full_qualified_month_share
- FAIL：locked_qualified_month_share
- FAIL：nonempty_snapshot_share
- PASS：minimum_nonempty_snapshot_rows
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows
- PASS：zero_ratio_range_violations
- PASS：zero_gap_violations

## 结论

REJECTED_BEFORE_BACKTEST。本阶段不计算收益，也不注册生产策略。
