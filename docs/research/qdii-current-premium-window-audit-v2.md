# QDII当前折溢价窗口归因 V2

- 窗口：20260601 至 20260728。
- 分类：PREMIUM_ELEVATED_NEAR_NORMALIZATION_LIMIT。
- 159941按组合60%权重完全归一化冲击：
  -5.95%。
- 仅为日频同日净值监控，不能替代盘中IOPV。

| 代码 | 匹配日 | 溢价中位 | P95 | 最新 | 超10%占比 |
|---|---:|---:|---:|---:|---:|
| 159941.SZ | 40 | 8.74% | 11.08% | 11.01% | 22.5% |
| 513500.SH | 40 | 5.12% | 7.37% | 5.92% | 0.0% |

## 冻结门槛

- PASS：each_symbol_has_at_least_30_matches
- PASS：all_nav_staleness_within_seven_days
- FAIL：nasdaq_latest_premium_within_10pct
- PASS：weighted_normalization_shock_within_6pct
- PASS：no_absolute_premium_above_50pct

当前风险标记不改写历史回测；它表示按最新场内价格追入，可能承担额外的
溢价回归损失。
