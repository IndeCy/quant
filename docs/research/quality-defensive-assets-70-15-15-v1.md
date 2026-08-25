# Quality + 黄金国债 70/15/15 V1

- 数据截止：20260617。
- 固定证券级组合：Quality Balanced Value 70%、黄金ETF 15%、5年国债ETF 15%。
- 三类证券统一qfq、T+1、M0和5bps；股票卖出收印花税，ETF免印花税。
- 核心与组合使用相同20日波动率风险层，防守袖套仅用于归因。
- 防守袖套与Quality相关性：0.044；
  组合与Quality相关性：0.950。
- 2015年核心首次降仓：20150528；
  混合组合首次降仓：20150709，
  晚29个交易日。

| 策略 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_balanced_value_core_same_snapshot_v1 | 2015_2017 | 24.96% | -25.44% | 1.043 | 0.981 | 75.72% | 10.45x |
| quality_balanced_value_core_same_snapshot_v1 | 2018_2020 | 3.67% | -24.55% | 0.281 | 0.149 | -22.73% | 5.69x |
| quality_balanced_value_core_same_snapshot_v1 | 2021_2023 | 5.32% | -24.87% | 0.375 | 0.214 | 47.57% | 5.82x |
| quality_balanced_value_core_same_snapshot_v1 | 2024_latest | 19.40% | -19.48% | 0.962 | 0.996 | -2.14% | 6.89x |
| quality_balanced_value_core_same_snapshot_v1 | full | 13.07% | -25.44% | 0.692 | 0.514 | 223.83% | 7.03x |
| gold_bond_equal_sleeve_v1 | 2015_2017 | 1.82% | -7.43% | 0.307 | 0.244 | -9.95% | 0.46x |
| gold_bond_equal_sleeve_v1 | 2018_2020 | 8.20% | -9.22% | 1.108 | 0.890 | -8.09% | 0.15x |
| gold_bond_equal_sleeve_v1 | 2021_2023 | 4.91% | -5.64% | 0.864 | 0.872 | 46.29% | 0.14x |
| gold_bond_equal_sleeve_v1 | 2024_latest | 17.19% | -15.54% | 1.462 | 1.106 | -8.67% | 0.26x |
| gold_bond_equal_sleeve_v1 | full | 7.55% | -15.54% | 0.968 | 0.486 | 58.88% | 0.24x |
| quality_defensive_assets_70_15_15_v1 | 2015_2017 | 11.10% | -34.56% | 0.634 | 0.321 | 20.46% | 7.82x |
| quality_defensive_assets_70_15_15_v1 | 2018_2020 | 5.49% | -17.42% | 0.452 | 0.315 | -16.98% | 4.13x |
| quality_defensive_assets_70_15_15_v1 | 2021_2023 | 5.65% | -16.81% | 0.493 | 0.336 | 48.64% | 4.19x |
| quality_defensive_assets_70_15_15_v1 | 2024_latest | 19.63% | -13.48% | 1.205 | 1.456 | -1.45% | 4.69x |
| quality_defensive_assets_70_15_15_v1 | full | 10.19% | -34.56% | 0.692 | 0.295 | 127.57% | 5.06x |

## 组合年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 28.03% | -32.79% | 1.006 |
| 2016 | 5.51% | -14.00% | 0.427 |
| 2017 | 6.79% | -9.23% | 0.802 |
| 2018 | -12.80% | -17.42% | -0.950 |
| 2019 | 20.74% | -11.78% | 1.543 |
| 2020 | 12.00% | -12.93% | 0.806 |
| 2021 | 17.17% | -10.83% | 1.328 |
| 2022 | -14.49% | -16.81% | -0.907 |
| 2023 | 14.83% | -5.17% | 1.578 |
| 2024 | 18.75% | -13.48% | 1.001 |
| 2025 | 19.13% | -7.92% | 1.544 |
| 2026 | 25.12% | -7.45% | 1.448 |

## 固定门槛

- PASS：full_annual_return_at_least_10pct
- FAIL：full_drawdown_within_25pct
- PASS：full_sharpe_at_least_065
- FAIL：full_calmar_at_least_040
- PASS：full_positive_excess
- PASS：at_least_three_positive_folds
- FAIL：worst_fold_drawdown_within_25pct
- PASS：median_fold_sharpe_at_least_035
- PASS：annual_turnover_below_8x
- FAIL：drawdown_improves_core_by_3pct
- FAIL：return_within_2_5pct_of_core
- FAIL：sharpe_not_below_core
- PASS：defensive_correlation_to_core_at_most_030
- PASS：at_least_nine_positive_years

- 相对核心回撤改善：-9.12%。
- 相对核心年化收益差：2.88%。

风险路径解释：防守资产压低了组合触发前的20日波动率，使同一45%阈值更晚生效。
本结果说明固定配置与非线性风险覆盖层不能分别验证后再直接拼接。

结论：终止，不进入生产。
