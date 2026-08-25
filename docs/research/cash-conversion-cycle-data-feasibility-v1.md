# 现金转换周期改善数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 完整候选最少/中位/最新：1359 /
  2284 / 3855。
- 完整覆盖率最少/中位/最新：90.02% /
  92.66% / 95.66%。
- 最新周期变化 P1/中位/P99：-355.48 /
  -0.86 / 318.31 天。
- 最新周期水平 P1/中位/P99：-251.41 /
  102.68 / 1321.61 天。
- 财务快照缺失/必需字段缺失：
  4.92% /
  7.33%。
- 公告越界/重复主键：0 /
  0。

## 冻结门槛

- PASS：full_qualified_month_share
- PASS：locked_qualified_month_share
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
