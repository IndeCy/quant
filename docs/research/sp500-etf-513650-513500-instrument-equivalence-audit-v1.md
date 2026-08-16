# 513650与513500标普500载体等价性 V1

- 区间：20230404 至 20260728；
  共同交易日：803。
- 日收益相关：0.9544；
  Beta：0.9403。
- 年化主动收益：-0.64%；
  年化跟踪误差：5.35%。
- 最差绝对单日主动收益：
  1.61%。
- 累计收益513650/513500：
  83.86% /
  87.38%。
- 分类：`INSTRUMENT_RETURN_EQUIVALENCE_FAILED`。

## 等价性门槛

- PASS：at_least_700_common_days
- FAIL：daily_return_correlation_at_least_098
- FAIL：beta_between_095_and_105
- PASS：annualized_active_return_within_2pct
- PASS：annualized_tracking_error_within_6pct
- PASS：worst_absolute_daily_active_return_within_5pct

本审计只验证历史日收益等价性；不授权替换机会成本对照或策略标的，
也不代表未来溢价和跟踪误差稳定。
