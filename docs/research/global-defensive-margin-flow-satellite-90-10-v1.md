# 全球防守核心 × 融资流卫星 90/10 V1

- 共同区间：20150105 至 20260723，
  2806 个交易日。
- 融资流单策略结论保持 `REJECTED`；本研究只验证10%硬上限组合。
- 袖套/Quality相关：0.191 /
  0.431。

| 区间 | 组合年化 | 组合回撤 | 组合Sharpe | 核心年化 |
|---|---:|---:|---:|---:|
| 2015_2017 | 7.44% | -8.72% | 1.058 | 6.15% |
| 2018_2020 | 10.04% | -11.32% | 1.238 | 10.08% |
| 2021_2023 | 7.96% | -5.49% | 1.197 | 7.63% |
| 2024_latest | 17.66% | -12.87% | 1.588 | 17.51% |
| full | 10.47% | -12.87% | 1.273 | 10.02% |

## 冻结门槛

- PASS `common_days_at_least_2500`
- PASS `sleeve_correlation_at_most_035`
- FAIL `quality_correlation_at_most_040`
- PASS `full_return_at_least_10pct`
- PASS `full_drawdown_within_15pct`
- PASS `full_sharpe_at_least_110`
- PASS `full_calmar_at_least_065`
- PASS `return_lift_vs_core_at_least_02pct`
- PASS `sharpe_shortfall_vs_core_within_005`
- PASS `drawdown_worse_vs_core_within_2pct`
- PASS `all_folds_positive`
- PASS `worst_fold_drawdown_within_17pct`
- PASS `median_fold_sharpe_at_least_075`
- PASS `at_least_nine_positive_years`
- PASS `allocation_turnover_below_05x`
- PASS `stress_return_at_least_95pct`
- PASS `stress_drawdown_within_16pct`
- PASS `stress_sharpe_at_least_100`

结论：`REJECTED_NO_SATELLITE_REVIVAL`。不复活融资流单策略，不接入scheduler或生产订单。
