# 机构席位净买入强度数据可行性 V1

- 数据截止：20260724，月末截面 30 个。
- 合格月份（全样本/2025年至今）：90.00% /
  100.00%。
- 正净买入候选最少/中位/最新：57 /
  144 / 215。
- 因子唯一值中位数：144；
  Top20 事件日中位数：1.2。
- 交易日同步成功/空结果占比：100.00% /
  0.00%；单日最多原始行：
  6160。
- 原始/去重后行数：523754 /
  245117，榜单展示重复占比：
  53.20%。
- 最新净买入强度 P1/中位/P99：0.0038 /
  0.1404 / 0.8228。
- 因子与成交额/波动率/120日收益的月度 Spearman 中位：
  -0.137 / -0.073 /
  -0.038。
- 事件键重复/净买入恒等式异常/未来可见性异常：
  0 /
  0 /
  0。

## 冻结门槛

- PASS：qualified_month_share
- PASS：locked_qualified_month_share
- PASS：checked_trade_day_share
- PASS：successful_trade_day_share
- PASS：source_row_limit_not_reached
- PASS：zero_duplicate_event_keys
- PASS：zero_net_buy_identity_violations
- PASS：zero_visibility_violations

## 结论

CONTINUE_TO_FULL_HISTORY_AND_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
