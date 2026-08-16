# Quality×盈利事件×黄金国债 60/10/15/15 V1

- 数据截止：20260727。
- 固定预算：Quality 60%、SUE事件 10%、黄金ETF 15%、五年国债ETF 15%。
- 权益袖套统一日频风险层；防守资产预算不随权益风险层缩放。
- 点时财务、股票前复权、基金不复权、M0 T+1；没有权重网格。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
| quality_defensive_assets_core_scoped_70_15_15_same_snapshot_v3 | 2015_2017 | 18.70% | -17.56% | 1.089 | 1.065 | 7.68x |
| quality_defensive_assets_core_scoped_70_15_15_same_snapshot_v3 | 2018_2020 | 5.51% | -17.38% | 0.453 | 0.317 | 4.12x |
| quality_defensive_assets_core_scoped_70_15_15_same_snapshot_v3 | 2021_2023 | 5.72% | -16.83% | 0.497 | 0.340 | 4.20x |
| quality_defensive_assets_core_scoped_70_15_15_same_snapshot_v3 | 2024_latest | 18.10% | -13.54% | 1.138 | 1.337 | 4.83x |
| quality_defensive_assets_core_scoped_70_15_15_same_snapshot_v3 | locked_test | 9.87% | -16.83% | 0.718 | 0.586 | 4.56x |
| quality_defensive_assets_core_scoped_70_15_15_same_snapshot_v3 | full | 11.90% | -17.56% | 0.825 | 0.678 | 5.04x |
| quality_defensive_event_60_10_15_15_v1 | 2015_2017 | 16.57% | -21.06% | 0.976 | 0.787 | 8.24x |
| quality_defensive_event_60_10_15_15_v1 | 2018_2020 | 5.62% | -17.97% | 0.458 | 0.313 | 4.65x |
| quality_defensive_event_60_10_15_15_v1 | 2021_2023 | 4.96% | -16.40% | 0.453 | 0.303 | 4.76x |
| quality_defensive_event_60_10_15_15_v1 | 2024_latest | 18.36% | -13.57% | 1.172 | 1.353 | 5.09x |
| quality_defensive_event_60_10_15_15_v1 | locked_test | 9.56% | -16.40% | 0.714 | 0.583 | 4.92x |
| quality_defensive_event_60_10_15_15_v1 | full | 11.25% | -21.06% | 0.791 | 0.534 | 5.52x |

## 诊断

- 事件有效月份占比：99.28%。
- 两股票袖套代码重叠中位数：
  0.00%。
- 20bps压力年化/Sharpe：
  10.25% / 0.732。
- 锁定期风格Beta/平均残差/最差残差：
  0.826 /
  5.37% /
  -13.83%。

## 冻结门槛

- PASS：full_annual_return_at_least_10pct
- PASS：full_drawdown_within_22pct
- PASS：full_sharpe_at_least_070
- PASS：full_calmar_at_least_045
- PASS：at_least_three_positive_folds
- PASS：worst_fold_drawdown_within_25pct
- PASS：median_fold_sharpe_at_least_040
- PASS：annual_turnover_below_8x
- PASS：locked_return_within_1pct_of_defensive_baseline
- FAIL：locked_sharpe_at_least_defensive_baseline
- FAIL：walk_forward_style_residual_gate_passed
- PASS：stress_20bps_annual_return_at_least_9pct
- PASS：stress_20bps_sharpe_at_least_060
- PASS：at_least_nine_positive_years

结论：REJECTED_NO_PRODUCTION_CHANGE。
