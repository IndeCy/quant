# 标普500高溢价归一化稳健性 V1

- 控制标的：`513500.SH`。
- 原重叠高溢价样本：
  194；高溢价月份：
  21。
- 月度中位为负占比：85.7%；
  月度中位数的中位：-1.35%。
- 月度聚类Bootstrap中位为负概率：
  100.0%。
- 非重叠事件：19；中位效应：
  -0.70%；负效应概率：
  57.9%。
- 分类：`NORMALIZATION_RISK_ROBUST_TO_OVERLAP_CONTROL`。

## 冻结门槛

- PASS：at_least_700_valid_observations
- PASS：at_least_10_high_premium_months
- PASS：negative_month_median_share_at_least_60pct
- PASS：bootstrap_cluster_median_negative_probability_at_least_80pct
- PASS：at_least_10_non_overlapping_events
- PASS：non_overlapping_median_effect_non_positive

本审计控制20日远期窗口重叠造成的伪精度，不构成择时信号或标的替换授权。
