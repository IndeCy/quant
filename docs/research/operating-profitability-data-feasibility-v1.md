# 经营盈利能力数据可行性 V1

- 数据截止：20260724，共 138 个月末截面。
- 候选数最少/中位/最新：1553 /
  2504 / 4027。
- 全样本/2022年后达标月份：100.00% /
  100.00%。
- 公告日越界/重复记录：0 /
  0。
- 销售/管理/利息费用缺失率：
  1.68% /
  0.00% /
  28.12%。
- 最新因子 P1/中位/P99：-0.8122 /
  0.0891 / 0.4482。

## 冻结门槛

- PASS：full_candidate_month_share
- PASS：locked_candidate_month_share
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows
- PASS：selling_expense_missing_within_limit
- PASS：admin_expense_missing_within_limit
- PASS：interest_expense_missing_within_limit
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
