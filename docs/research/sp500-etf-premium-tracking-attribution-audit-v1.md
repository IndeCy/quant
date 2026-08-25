# 标普500 ETF溢价与净值跟踪归因 V1

- 区间：20230404 至 20260728；共同净值区间：
  801。
- 场内价格日收益相关：0.9544；
  单位净值日收益相关：0.9998。
- 单位净值Beta：0.9970；
  年化跟踪误差：0.30%。
- 场内主动收益与溢价变化差的相关：
  0.9984。
- 最新513650/513500溢价：
  4.67% /
  5.92%；差：
  -1.25%。
- 分解最大绝对误差：
  4.441e-16。
- 分类：`PREMIUM_DYNAMICS_DOMINATE_RETURN_DIVERGENCE`。

## 冻结门槛

- PASS：at_least_700_common_intervals
- PASS：source_raw_correlation_remains_below_098
- PASS：unit_nav_return_correlation_at_least_098
- PASS：unit_nav_beta_between_095_and_105
- PASS：unit_nav_tracking_error_within_3pct
- PASS：active_price_is_linked_to_active_premium_effect
- PASS：decomposition_error_within_1e_10

本审计只归因已观察到的收益偏差，不推翻等价性失败，不授权替换标的，
也不使用或修改生产数据库。
