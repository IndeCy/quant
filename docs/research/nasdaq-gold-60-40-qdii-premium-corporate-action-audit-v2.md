# 纳指黄金QDII公司行动对齐折溢价审计 V2

- 固定清洗：仅排除复权因子切换日前后各一条记录；不按收益或溢价大小删点。
- 原始数据库未修改，源策略研究门槛不覆盖。

| 代码 | 资产 | 排除行数 | 排除日期 | 清洗后最大溢价 | 未解释>|50%|行 |
|---|---|---:|---|---:|---:|
| 159941.SZ | 纳斯达克100ETF | 4 | 20180115, 20180116, 20220704, 20220705 | 25.16% | 0 |
| 513500.SH | 标普500ETF对照 | 7 | 20180112, 20180115, 20200917, 20200918, 20200921, 20220328, 20220330 | 36.34% | 0 |

## 对60/40组合的清洗后影响

- 全期年化溢价变化贡献：0.52%
- 252日滚动年化贡献绝对尾部：
  3.85%
- 最后已知溢价归零冲击：-2.82%
- NAV最后日期：20260611；之后实时溢价未知。

## 冻结门槛

- PASS：all_nav_coverage_at_least_95pct
- PASS：all_nav_staleness_within_60_days
- PASS：all_median_absolute_premium_within_3pct
- PASS：nasdaq_month_end_above_5pct_share_within_20pct
- PASS：weighted_full_annual_premium_contribution_within_1pct
- PASS：weighted_rolling_annual_contribution_tail_within_5pct
- PASS：last_known_normalization_shock_within_6pct
- PASS：zero_unexplained_absolute_premium_above_50pct
- PASS：all_excluded_shares_within_1pct

结论：公司行动错位已被固定规则解释，历史折溢价风险仍在冻结范围内。
