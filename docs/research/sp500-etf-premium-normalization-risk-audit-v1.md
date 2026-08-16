# 标普500 ETF高溢价归一化风险 V1

- 区间：20230404 至 20260728。
- 固定高溢价阈值：5.0%；
  观察未来：20个交易日。
- 分类：`CONTROL_PREMIUM_NORMALIZATION_RISK_CANDIDATE_CURRENTLY_LOWER`。

| 代码 | 最新溢价 | 历史分位 | 高溢价样本 | 20日效应中位 | 负效应概率 | 损失超2%概率 |
|---|---:|---:|---:|---:|---:|---:|
| 513650.SH | 4.67% | 92.9% | 37 | -1.99% | 94.6% | 48.6% |
| 513500.SH | 5.92% | 80.3% | 194 | -1.23% | 74.2% | 37.1% |

## 冻结门槛

- PASS：each_symbol_has_at_least_700_valid_observations
- PASS：control_has_at_least_50_high_premium_observations
- PASS：control_high_premium_negative_probability_at_least_60pct
- PASS：control_high_premium_median_effect_non_positive
- PASS：candidate_latest_premium_within_5pct
- PASS：control_latest_premium_at_least_5pct
- PASS：no_absolute_premium_above_50pct

“溢价效应”只隔离场内价格相对单位净值的变化，不是基金总收益，也不构成
择时信号或自动替换授权。
