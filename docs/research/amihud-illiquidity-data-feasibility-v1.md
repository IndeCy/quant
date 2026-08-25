# Amihud 非流动性数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 成交额由 Tushare 千元转换为人民币；因子越高代表单位成交额价格冲击越大。
- 候选最少/中位/最新：1441 /
  2476 / 4030。
- 唯一值最少：1441；
  单日冲击集中度中位数最大值：
  27.34%。
- Top40月度日均成交额中位数最低值：
  13.1百万元；
  高于500万元的持仓比例最低值：
  97.5%。
- 最新因子 P1/中位/P99：4.586e-12 /
  1.106e-10 /
  5.295e-10。
- 与20日成交额/60日波动/120日收益 Spearman 中位数：
  -0.774 /
  0.065 /
  -0.058。
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

CONTINUE_TO_FIXED_BACKTEST。本阶段没有运行收益回测，也没有注册生产策略。
