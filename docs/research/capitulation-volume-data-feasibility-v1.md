# 放量下跌恐慌反转数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 全部候选最少/中位/最新：1390 /
  2476 / 4030。
- 放量下跌候选最少/中位/最新：17 /
  315 / 734。
- 最新异常成交比 P1/中位/P99：1.00 /
  1.26 / 4.04。
- 最新20日收益 P1/中位/P99：-35.31% /
  -11.96% / -0.32%。
- 收益与异常成交比月度 Spearman 中位数：
  0.441。
- 重复主键/窗口长度异常：0 /
  0。

## 冻结门槛

- PASS：full_qualified_month_share
- PASS：locked_qualified_month_share
- PASS：zero_duplicate_signal_symbol_rows
- PASS：zero_window_length_violations
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
