# 净现金财务韧性数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 候选最少/中位/最新：1407 /
  2384 / 3933。
- 唯一因子值最少：1407；
  Top40债务字段全部未报告占比最大值：
  77.5%。
- Top40月度日均成交额中位数最低值：
  38.7百万元；
  高于500万元的持仓比例最低值：
  100.0%。
- 最新净现金资产比 P1/中位/P99：
  -0.543 /
  0.010 /
  0.553。
- 最新全债务字段未报告/有息债务为零占比：
  2.0% /
  2.1%。
- 与20日成交额/60日波动/120日收益 Spearman 中位数：
  -0.008 /
  0.054 /
  0.015。
- 重复主键/未来可见/范围异常：
  0 /
  0 /
  727。

## 冻结门槛

- FAIL：full_qualified_month_share
- PASS：locked_qualified_month_share
- PASS：zero_duplicate_signal_symbol_rows
- PASS：zero_visibility_violations
- FAIL：zero_range_violations
- PASS：finite_latest_distribution

## 结论

REJECTED_BEFORE_BACKTEST。本阶段没有运行收益回测，也没有注册生产策略。
