# 官方源净流入数据可行性 V1

- 数据截止：20260724，月末截面 30 个。
- 合格月份（全样本/2025年至今）：16.67% /
  16.67%。
- 正净流入候选最少/中位/最新：365 /
  672 / 657。
- 因子唯一值中位数：672。
- 交易日同步成功率/单日最多行：
  100.00% /
  5198。
- 全档买卖差近零占比：100.00%。
- 分类金额/行情成交额 P1/中位/P99：
  2.000 /
  2.000 /
  2.000。
- 最新源净流入占比 P1/中位/P99：0.0002 /
  0.0145 / 0.0693。
- 与成交额/波动率/20日收益/120日收益/旧成交额压力的Spearman中位：
  0.058 / -0.200 /
  0.209 / 0.047 /
  0.198。
- 重复/未来可见性/源净流入范围异常：
  0 /
  0 /
  15。

## 说明

`net_mf_amount` 是数据商给出的净流入字段，内部主动买卖判定方法不透明。
本研究只验证它是否稳定、独立且可回测，不把它解释为可直接观察的真实机构买卖。

## 冻结门槛

- FAIL：qualified_month_share
- FAIL：locked_qualified_month_share
- PASS：checked_trade_day_share
- PASS：successful_trade_day_share
- PASS：source_row_limit_not_reached
- PASS：symmetric_bucket_contract
- PASS：classified_amount_is_double_turnover
- PASS：distinct_from_signed_amount_proxy
- PASS：zero_duplicate_daily_rows
- PASS：zero_visibility_violations
- FAIL：zero_source_share_range_violations

## 结论

REJECTED_BEFORE_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
