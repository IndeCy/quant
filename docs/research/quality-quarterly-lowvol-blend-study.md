# Quality Quarterly LowVol Blend V1 Study

- 数据截止：20260723
- 固定组合：Quality Balanced Value核心70% + 季度正动量低波卫星30%。
- 两条腿保持各自原始因子和选股频率，组合层只合并目标权重。
- 统一口径：qfq、M0 T+1、5bps及20日组合波动率风险层。
- 核心与卫星日收益相关性：0.784。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_balanced_value_core_v1 | validation | 21.23% | -22.96% | 1.092 | 0.925 | 0.64% | 598.02% |
| quality_balanced_value_core_v1 | locked_test | 8.74% | -24.84% | 0.522 | 0.352 | 38.18% | 634.27% |
| quality_balanced_value_core_v1 | full | 13.16% | -25.46% | 0.696 | 0.517 | 237.75% | 697.14% |
| quarterly_positive_momentum_lowvol_satellite_v1 | validation | 14.54% | -16.95% | 0.982 | 0.858 | -25.88% | 653.15% |
| quarterly_positive_momentum_lowvol_satellite_v1 | locked_test | 10.34% | -13.15% | 0.761 | 0.786 | 47.72% | 644.83% |
| quarterly_positive_momentum_lowvol_satellite_v1 | full | 7.44% | -44.23% | 0.509 | 0.168 | 63.69% | 674.64% |
| quality_quarterly_lowvol_blend_v1 | validation | 19.19% | -20.91% | 1.099 | 0.918 | -7.75% | 619.57% |
| quality_quarterly_lowvol_blend_v1 | locked_test | 9.28% | -20.86% | 0.598 | 0.445 | 41.35% | 652.88% |
| quality_quarterly_lowvol_blend_v1 | full | 12.76% | -27.96% | 0.720 | 0.456 | 222.37% | 730.22% |

## 组合年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 78.48% | -26.49% | 1.903 |
| 2016 | 12.95% | -13.85% | 0.697 |
| 2017 | 10.10% | -10.34% | 1.001 |
| 2018 | -24.96% | -27.96% | -1.584 |
| 2019 | 21.43% | -17.22% | 1.249 |
| 2020 | 10.86% | -16.57% | 0.618 |
| 2021 | 24.00% | -12.58% | 1.500 |
| 2022 | -17.35% | -20.86% | -0.838 |
| 2023 | 16.45% | -7.73% | 1.391 |
| 2024 | 21.28% | -15.23% | 0.999 |
| 2025 | 12.77% | -10.41% | 0.927 |
| 2026 | 25.42% | -11.63% | 1.435 |

## 固定晋级门槛

- PASS：full_annual_return_at_least_10pct
- PASS：full_sharpe_at_least_065
- PASS：full_drawdown_within_30pct
- PASS：locked_test_positive_excess
- PASS：annual_turnover_below_8x
- PASS：at_least_nine_positive_years
- FAIL：full_drawdown_improves_core_by_3pct
- PASS：full_return_within_1_5pct_of_core
- PASS：full_sharpe_not_below_core
- PASS：locked_drawdown_not_worse_than_core_2pct

结论：终止，不注册生产策略。
