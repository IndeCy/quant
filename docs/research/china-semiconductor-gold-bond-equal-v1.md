# 半导体黄金国债固定三等权 V1

- 固定持有半导体ETF、黄金ETF、5年国债ETF，各三分之一。
- 月末恢复等权；无择时、无排名、无权重网格。
- M0 T+1、基础5bps、压力20bps；数据截止20260728。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2020_2021 | 11.02% | -16.39% | 0.795 | 0.673 | 0.91x |
| 2022_2023 | -1.85% | -13.05% | -0.117 | -0.141 | 0.36x |
| 2024_latest | 29.42% | -14.15% | 1.649 | 2.080 | 0.67x |
| locked_test | 29.42% | -14.15% | 1.649 | 2.080 | 0.67x |
| full | 13.31% | -18.42% | 0.941 | 0.722 | 0.65x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| china_semiconductor_gold_bond_equal_v1 | 13.31% | -18.42% | 0.941 |
| semiconductor_study_gold_bond_equal_control | 8.93% | -16.58% | 1.011 |
| semiconductor_direct_three_asset_control | 15.09% | -62.49% | 0.559 |
| sp500_direct_semiconductor_three_asset_control | 14.88% | -29.26% | 0.812 |
| global_defensive_same_period_control | 11.27% | -12.97% | 1.205 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2020 | 13.81% | -14.88% | 0.874 |
| 2021 | 7.09% | -11.18% | 0.620 |
| 2022 | -9.26% | -13.05% | -0.771 |
| 2023 | 5.61% | -9.39% | 0.599 |
| 2024 | 23.85% | -9.01% | 1.574 |
| 2025 | 37.13% | -5.87% | 2.374 |
| 2026 | 23.96% | -14.15% | 1.048 |

## 尾部与独立性

- 年化波动：14.38%
- 最差单日：-5.37%
- 95% Expected Shortfall：-1.99%
- 最长水下期：767日
- 与Quality日收益相关性：0.326

## 冻结门槛

- PASS：data_audit
- PASS：full_return_at_least_9pct
- PASS：full_drawdown_within_24pct
- PASS：full_sharpe_at_least_075
- PASS：full_calmar_at_least_035
- PASS：return_lift_vs_gold_bond_at_least_1pct
- PASS：drawdown_improvement_vs_semiconductor_at_least_15pct
- PASS：sharpe_lift_vs_semiconductor_at_least_010
- PASS：return_shortfall_vs_sp500_within_3pct
- PASS：return_shortfall_vs_global_within_2pct
- FAIL：sharpe_shortfall_vs_global_within_010
- FAIL：all_three_folds_positive
- PASS：worst_fold_drawdown_within_25pct
- PASS：median_fold_sharpe_at_least_060
- PASS：locked_return_at_least_9pct
- PASS：locked_drawdown_within_20pct
- PASS：locked_sharpe_at_least_075
- PASS：at_least_five_positive_years
- PASS：annual_turnover_below_1x
- PASS：stress_return_at_least_8pct
- PASS：stress_sharpe_at_least_070
- PASS：worst_day_within_8pct
- PASS：expected_shortfall_95_within_3pct
- PASS：quality_correlation_at_most_050

结论：未通过冻结门槛，归档且不注册。
