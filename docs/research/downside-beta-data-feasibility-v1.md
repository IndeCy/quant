# 低下行 Beta 数据与排重可行性 V1

- 数据截止：20260724，月末截面 129 个。
- 252日窗口至少200个总样本、60个沪深300下跌日；越低越防御。
- 候选最少/中位/最新：448 /
  2410 / 3886。
- 唯一因子值最少：448。
- Top40月度日均成交额中位数最低值：
  39.7百万元；
  高于500万元的持仓比例最低值：
  100.0%。
- 最新下行 Beta P1/中位/P99：
  0.105 /
  0.964 /
  2.569。
- 最新总 Beta / 上行 Beta 中位数：
  0.830 /
  0.721。
- 与低总Beta/低60日波动 Spearman 中位数：
  0.674 /
  0.265；
  Top40重合：
  25.0% /
  5.0%。
- 与成交额/120日动量 Spearman 中位数：
  -0.029 /
  0.000。
- 重复主键/窗口异常：
  0 /
  0。

## 冻结门槛

- PASS：full_qualified_month_share
- PASS：locked_qualified_month_share
- PASS：distinct_from_low_total_beta
- PASS：distinct_from_low_vol60
- PASS：zero_duplicate_signal_symbol_rows
- PASS：zero_observation_violations
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段没有运行收益回测，也没有注册生产策略。
