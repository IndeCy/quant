# A股因子换手分层锁定期存活审计 V1

- 来源家族：31。
- 分类：LOWER_TURNOVER_HELPS_BUT_IS_NOT_SUFFICIENT。
- 换手与锁定收益Spearman：
  -0.205。
- 低换手减高换手的锁定收益中位差：
  9.15%。

| 换手层 | 家族数 | 换手中位 | 验证收益中位 | 锁定收益中位 | 锁定正收益 | 锁定过门槛 |
|---|---:|---:|---:|---:|---:|---:|
| low_le_8x | 12 | 6.01x | 14.55% | -3.71% | 25.0% | 0 |
| medium_8_to_15x | 9 | 8.96x | 19.44% | -2.57% | 44.4% | 0 |
| high_gt_15x | 10 | 19.50x | 12.53% | -12.87% | 10.0% | 0 |

## 描述性门槛

- PASS：source_has_at_least_30_experiments
- PASS：all_turnover_buckets_nonempty
- PASS：low_locked_return_advantage_at_least_3pct
- PASS：low_positive_ratio_exceeds_high

低换手若有优势也只代表摩擦和稳定性改善，不构成Alpha来源；本审计不重新
分类任何源策略，也不把低频本身当作晋级理由。
