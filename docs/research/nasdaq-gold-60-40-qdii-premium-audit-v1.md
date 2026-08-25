# 纳指黄金60/40跨境ETF折溢价审计 V1

- 场内回测价格本身已包含折溢价，本审计不重算或覆盖源策略门槛。
- 溢价定义：原始收盘价/单位净值-1；净值反事实不可直接成交。
- 审计截止：20260728。

| 代码 | 资产 | NAV覆盖 | 最后NAV日 | 溢价中位 | 溢价P95 | 最大溢价 | 最后已知溢价 |
|---|---|---:|---|---:|---:|---:|---:|
| 159941.SZ | 纳斯达克100ETF | 98.31% | 20260611 | 0.25% | 6.36% | 297.86% | 4.93% |
| 513500.SH | 标普500ETF对照 | 97.05% | 20260611 | 0.23% | 7.27% | 36.34% | 4.78% |

## 对60/40组合的影响

- 全期年化溢价变化贡献（60%权重近似）：
  0.52%
- 252日滚动年化贡献绝对尾部（60%权重近似）：
  3.89%
- 最后已知溢价瞬间归零的组合冲击：
  -2.82%
- 最后净值日期：20260611；此后当前溢价为
  `UNKNOWN`，不能用旧NAV外推。

## 冻结门槛

- PASS：all_nav_coverage_at_least_95pct
- PASS：all_nav_staleness_within_60_days
- PASS：all_median_absolute_premium_within_3pct
- PASS：nasdaq_month_end_above_5pct_share_within_20pct
- PASS：weighted_full_annual_premium_contribution_within_1pct
- PASS：weighted_rolling_annual_contribution_tail_within_5pct
- PASS：last_known_normalization_shock_within_6pct

结论：折溢价风险在冻结范围内，但仍需实盘下单前检查实时IOPV/NAV。
