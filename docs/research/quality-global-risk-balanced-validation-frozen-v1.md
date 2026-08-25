# 国内Quality×全球防守校准期风险平衡 V1

- 数据截止：20260728
- 权重仅由2015–2018日波动率按逆波动公式产生，2019后冻结。
- Quality/全球块冻结权重：
  22.13% /
  77.87%。
- 不做权重网格，不读取锁定期定权。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---|---:|---:|---:|---:|
| quality_calibration_block_same_snapshot_v1 | 2019_2021 | 21.23% | -22.97% | 1.092 | 5.98x |
| quality_calibration_block_same_snapshot_v1 | 2022_2024 | 2.72% | -24.86% | 0.233 | 6.26x |
| quality_calibration_block_same_snapshot_v1 | 2025_latest | 22.10% | -12.91% | 1.257 | 6.40x |
| quality_calibration_block_same_snapshot_v1 | locked_test | 8.47% | -24.86% | 0.509 | 6.32x |
| quality_calibration_block_same_snapshot_v1 | oos_full | 13.75% | -24.86% | 0.753 | 6.21x |
| global_defensive_calibration_block_same_snapshot_v1 | 2019_2021 | 11.95% | -11.85% | 1.468 | 0.30x |
| global_defensive_calibration_block_same_snapshot_v1 | 2022_2024 | 12.69% | -6.48% | 1.636 | 0.27x |
| global_defensive_calibration_block_same_snapshot_v1 | 2025_latest | 12.28% | -12.97% | 1.014 | 0.39x |
| global_defensive_calibration_block_same_snapshot_v1 | locked_test | 12.71% | -12.97% | 1.327 | 0.32x |
| global_defensive_calibration_block_same_snapshot_v1 | oos_full | 12.41% | -12.97% | 1.373 | 0.32x |
| quality_global_risk_balanced_validation_frozen_v1 | 2019_2021 | 14.25% | -11.36% | 1.647 | 1.58x |
| quality_global_risk_balanced_validation_frozen_v1 | 2022_2024 | 10.93% | -7.90% | 1.348 | 1.62x |
| quality_global_risk_balanced_validation_frozen_v1 | 2025_latest | 14.51% | -10.08% | 1.212 | 1.72x |
| quality_global_risk_balanced_validation_frozen_v1 | locked_test | 12.16% | -10.08% | 1.265 | 1.66x |
| quality_global_risk_balanced_validation_frozen_v1 | oos_full | 13.07% | -11.36% | 1.411 | 1.64x |

## 风险与成本

- 校准期Quality/全球年化波动：
  23.18% /
  6.59%。
- 样本外候选与Quality/全球相关：
  0.678 /
  0.886。
- 锁定期Quality/全球风险贡献：
  31.26% /
  68.74%。
- 20bps压力年化/Sharpe：
  12.85% / 1.391。

## 冻结门槛

- PASS：oos_return_at_least_9pct
- PASS：oos_drawdown_within_16pct
- PASS：oos_sharpe_at_least_100
- PASS：oos_calmar_at_least_060
- PASS：all_three_folds_positive
- PASS：worst_fold_drawdown_within_18pct
- PASS：median_fold_sharpe_at_least_075
- PASS：annual_turnover_below_3_5x
- PASS：locked_return_at_least_9pct
- PASS：locked_drawdown_within_15pct
- PASS：locked_sharpe_at_least_090
- PASS：candidate_quality_correlation_at_most_088
- PASS：locked_quality_risk_contribution_between_25_and_75pct
- PASS：return_at_least_global_minus_05pct
- PASS：sharpe_at_least_quality_block
- PASS：stress_return_at_least_8pct
- PASS：stress_sharpe_at_least_090
- PASS：at_least_six_positive_years

结论：HISTORICAL_GATE_PASSED_FORWARD_CONFIRMATION_ONLY。
