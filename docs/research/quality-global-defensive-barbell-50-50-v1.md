# 国内Quality×全球防守固定杠铃50/50 V1

- 数据截止：20260728
- 国内Quality 50%；标普500、黄金、5年国债各16.67%。
- Quality风险层只管理国内股票块；三个ETF固定预算。
- 没有权重网格，不自动修改观察策略或生产调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---|---:|---:|---:|---:|
| quality_defensive_70_15_15_same_snapshot_v3 | 2015_2017 | 18.72% | -17.54% | 1.090 | 7.68x |
| quality_defensive_70_15_15_same_snapshot_v3 | 2018_2020 | 5.53% | -17.36% | 0.454 | 4.11x |
| quality_defensive_70_15_15_same_snapshot_v3 | 2021_2023 | 5.71% | -16.85% | 0.496 | 4.20x |
| quality_defensive_70_15_15_same_snapshot_v3 | 2024_latest | 18.29% | -13.54% | 1.148 | 4.82x |
| quality_defensive_70_15_15_same_snapshot_v3 | locked_test | 9.96% | -16.85% | 0.724 | 4.56x |
| quality_defensive_70_15_15_same_snapshot_v3 | full | 11.95% | -17.54% | 0.828 | 5.04x |
| global_defensive_equal_same_snapshot_v2 | 2015_2017 | 6.14% | -9.50% | 0.910 | 0.55x |
| global_defensive_equal_same_snapshot_v2 | 2018_2020 | 10.07% | -11.85% | 1.257 | 0.30x |
| global_defensive_equal_same_snapshot_v2 | 2021_2023 | 7.60% | -6.48% | 1.124 | 0.26x |
| global_defensive_equal_same_snapshot_v2 | 2024_latest | 16.83% | -12.97% | 1.495 | 0.35x |
| global_defensive_equal_same_snapshot_v2 | locked_test | 12.71% | -12.97% | 1.327 | 0.32x |
| global_defensive_equal_same_snapshot_v2 | full | 9.88% | -12.97% | 1.203 | 0.35x |
| quality_global_defensive_barbell_50_50_v1 | 2015_2017 | 16.28% | -13.26% | 1.211 | 5.71x |
| quality_global_defensive_barbell_50_50_v1 | 2018_2020 | 7.26% | -12.96% | 0.650 | 3.05x |
| quality_global_defensive_barbell_50_50_v1 | 2021_2023 | 6.99% | -13.48% | 0.703 | 3.09x |
| quality_global_defensive_barbell_50_50_v1 | 2024_latest | 18.66% | -9.12% | 1.383 | 3.56x |
| quality_global_defensive_barbell_50_50_v1 | locked_test | 11.19% | -13.48% | 0.941 | 3.37x |
| quality_global_defensive_barbell_50_50_v1 | full | 12.16% | -13.48% | 1.007 | 3.71x |

## 独立性和成本

- 候选与Quality/全球防守日收益相关：
  0.946 / 0.535。
- Quality与全球防守日收益相关：0.234。
- 20bps压力年化/Sharpe：
  11.51% / 0.959。

## 冻结门槛

- PASS：full_return_at_least_10pct
- PASS：full_drawdown_within_18pct
- PASS：full_sharpe_at_least_090
- PASS：full_calmar_at_least_055
- PASS：all_four_folds_positive
- PASS：worst_fold_drawdown_within_20pct
- PASS：median_fold_sharpe_at_least_050
- PASS：annual_turnover_below_5x
- PASS：locked_return_at_least_9pct
- PASS：locked_sharpe_at_least_070
- PASS：locked_drawdown_within_18pct
- PASS：return_within_1pct_of_quality_defensive
- PASS：drawdown_improves_quality_defensive_by_2pct
- PASS：sharpe_at_least_quality_defensive
- PASS：return_at_least_global_defensive
- FAIL：quality_daily_correlation_at_most_075
- PASS：global_daily_correlation_at_most_090
- PASS：stress_20bps_return_at_least_9pct
- PASS：stress_20bps_sharpe_at_least_080
- PASS：at_least_nine_positive_years

结论：REJECTED_NO_PRODUCTION_CHANGE。
