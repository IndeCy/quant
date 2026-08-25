# 真实大单资金流数据可行性 V1

- 数据截止：20260724，月末截面 30 个。
- 合格月份（全样本/2025年至今）：50.00% /
  72.22%。
- 正大单流候选最少/中位/最新：464 /
  992 / 1547。
- 因子唯一值中位数：992。
- 交易日同步成功/空结果占比：100.00% /
  0.00%；单日最多原始行：
  5198。
- 全订单净额与源净流入恒等式异常占比：
  100.00%。
- 分类金额/行情成交额 P1/中位/P99：
  2.000 /
  2.000 /
  2.000。
- 最新大单净流入占比 P1/中位/P99：0.0001 /
  0.0054 / 0.0247。
- 与成交额/波动率/20日收益/120日收益/旧成交额压力的Spearman中位：
  -0.055 / -0.015 /
  0.122 / 0.007 /
  0.036。
- 缓存重复/未来可见性/因子范围异常：
  0 /
  0 /
  0。

## 冻结门槛

- FAIL：qualified_month_share
- FAIL：locked_qualified_month_share
- PASS：checked_trade_day_share
- PASS：successful_trade_day_share
- PASS：source_row_limit_not_reached
- FAIL：net_identity_consistent
- FAIL：turnover_amount_consistent
- PASS：distinct_from_signed_amount_proxy
- PASS：zero_duplicate_daily_rows
- PASS：zero_visibility_violations
- PASS：zero_factor_range_violations

## 结论

REJECTED_BEFORE_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
