# Quality防守袖套风险预算 V2

- 数据截止：20260723。
- 固定预算：Quality 70%、黄金ETF 15%、5年国债ETF 15%。
- 正常期总仓位100%；核心风险层触发后为Quality 21%、防守30%、现金49%。
- 风险参数保持20日、45%阈值、核心降至30%，不修改Alpha和M0。

| 策略 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_balanced_value_core_same_snapshot_v1 | 2015_2017 | 24.97% | -25.46% | 1.043 | 0.981 | 75.77% | 10.45x |
| quality_balanced_value_core_same_snapshot_v1 | 2018_2020 | 3.68% | -24.54% | 0.281 | 0.150 | -22.72% | 5.69x |
| quality_balanced_value_core_same_snapshot_v1 | 2021_2023 | 5.34% | -24.84% | 0.376 | 0.215 | 47.62% | 5.82x |
| quality_balanced_value_core_same_snapshot_v1 | 2024_latest | 19.52% | -19.47% | 0.964 | 1.003 | 6.25% | 6.72x |
| quality_balanced_value_core_same_snapshot_v1 | full | 13.16% | -25.46% | 0.696 | 0.517 | 237.75% | 6.97x |
| gold_bond_equal_sleeve_v1 | 2015_2017 | 1.83% | -7.44% | 0.309 | 0.246 | -9.92% | 0.49x |
| gold_bond_equal_sleeve_v1 | 2018_2020 | 8.20% | -9.22% | 1.108 | 0.890 | -8.10% | 0.16x |
| gold_bond_equal_sleeve_v1 | 2021_2023 | 4.90% | -5.64% | 0.862 | 0.869 | 46.25% | 0.15x |
| gold_bond_equal_sleeve_v1 | 2024_latest | 15.49% | -16.58% | 1.337 | 0.934 | -6.26% | 0.27x |
| gold_bond_equal_sleeve_v1 | full | 7.28% | -16.58% | 0.934 | 0.439 | 60.07% | 0.26x |
| quality_defensive_assets_whole_overlay_same_snapshot_v1 | 2015_2017 | 11.15% | -34.55% | 0.636 | 0.323 | 20.63% | 7.79x |
| quality_defensive_assets_whole_overlay_same_snapshot_v1 | 2018_2020 | 5.53% | -17.37% | 0.454 | 0.318 | -16.88% | 4.13x |
| quality_defensive_assets_whole_overlay_same_snapshot_v1 | 2021_2023 | 5.64% | -16.83% | 0.492 | 0.335 | 48.60% | 4.19x |
| quality_defensive_assets_whole_overlay_same_snapshot_v1 | 2024_latest | 19.16% | -13.49% | 1.178 | 1.421 | 5.11% | 4.58x |
| quality_defensive_assets_whole_overlay_same_snapshot_v1 | full | 10.19% | -34.55% | 0.692 | 0.295 | 136.08% | 5.01x |
| quality_defensive_assets_core_scoped_70_15_15_v2 | 2015_2017 | 18.72% | -17.54% | 1.090 | 1.067 | 49.30% | 7.68x |
| quality_defensive_assets_core_scoped_70_15_15_v2 | 2018_2020 | 5.53% | -17.36% | 0.454 | 0.318 | -16.88% | 4.11x |
| quality_defensive_assets_core_scoped_70_15_15_v2 | 2021_2023 | 5.71% | -16.85% | 0.496 | 0.339 | 48.83% | 4.21x |
| quality_defensive_assets_core_scoped_70_15_15_v2 | 2024_latest | 18.86% | -13.55% | 1.183 | 1.392 | 4.15% | 4.85x |
| quality_defensive_assets_core_scoped_70_15_15_v2 | full | 12.06% | -17.54% | 0.835 | 0.688 | 196.78% | 5.05x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 45.31% | -17.40% | 1.699 |
| 2016 | 13.13% | -9.59% | 0.918 |
| 2017 | 6.75% | -9.20% | 0.801 |
| 2018 | -12.80% | -17.36% | -0.952 |
| 2019 | 20.87% | -11.74% | 1.550 |
| 2020 | 11.98% | -12.94% | 0.805 |
| 2021 | 17.38% | -10.87% | 1.340 |
| 2022 | -14.50% | -16.85% | -0.904 |
| 2023 | 14.82% | -5.17% | 1.576 |
| 2024 | 17.82% | -13.55% | 0.990 |
| 2025 | 19.13% | -7.91% | 1.544 |
| 2026 | 22.11% | -10.63% | 1.291 |

## 固定门槛

- PASS：full_annual_return_at_least_10pct
- PASS：full_drawdown_within_25pct
- PASS：full_sharpe_at_least_065
- PASS：full_calmar_at_least_040
- PASS：full_positive_excess
- PASS：at_least_three_positive_folds
- PASS：worst_fold_drawdown_within_25pct
- PASS：median_fold_sharpe_at_least_035
- PASS：annual_turnover_below_8x
- PASS：drawdown_improves_core_by_3pct
- PASS：drawdown_improves_whole_overlay_by_5pct
- PASS：return_within_2_5pct_of_core
- PASS：sharpe_not_below_core
- PASS：at_least_nine_positive_years

- 相对纯核心回撤变化：7.92%。
- 相对整组合覆盖层回撤变化：17.01%。
- 相对纯核心年化收益差：1.10%。

结论：通过研究门槛，仅进入前瞻确认。
