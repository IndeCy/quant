# 成交额加权涨跌压力数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 候选最少/中位/最新：1457 /
  2476 / 4030。
- 唯一因子值最少：1457；
  单日成交额集中度月度中位数最大值：
  18.23%。
- 最新压力 P1/中位/P99：-0.613 /
  -0.105 /
  0.571。
- 最新20日收益 P1/中位/P99：-32.58% /
  -9.62% / 84.85%。
- 与20日收益的月度 Spearman 中位数：
  0.683。
- 重复主键/窗口异常/范围异常：
  0 /
  0 /
  0。

## 冻结门槛

- PASS：full_qualified_month_share
- PASS：locked_qualified_month_share
- PASS：zero_duplicate_signal_symbol_rows
- PASS：zero_window_length_violations
- PASS：zero_range_violations
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
