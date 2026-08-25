# Fundamental Strength Value V1 Study

- 数据截止：20260722
- 主策略固定：基本面强度70% + 点时E/P、B/P共30%，Top40等权，月频。
- 归因对照：基本面强度单腿、价值单腿和Quality V1，仅解释收益来源，不参与选参。
- 统一口径：年报f_ann_date as-of、公司行动门禁、qfq、M0 T+1、5bps及原风险层。
- 公司行动门禁：检查341118条，剔除29873条，缺失4642条。
- 与Quality V1日收益相关性：0.859。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| fundamental_strength_only_v1 | validation | 29.77% | -19.56% | 1.333 | 1.522 | 38.72% | 361.87% |
| fundamental_strength_only_v1 | locked_test | -1.59% | -31.39% | 0.023 | -0.051 | -12.33% | 405.20% |
| fundamental_strength_only_v1 | full | 9.85% | -40.57% | 0.523 | 0.243 | 126.54% | 535.02% |
| point_in_time_value_only_v1 | validation | 11.63% | -30.13% | 0.618 | 0.386 | -36.52% | 559.48% |
| point_in_time_value_only_v1 | locked_test | 1.95% | -27.66% | 0.197 | 0.071 | 3.24% | 586.07% |
| point_in_time_value_only_v1 | full | 7.85% | -38.08% | 0.452 | 0.206 | 73.91% | 638.68% |
| fundamental_strength_value_v1 | validation | 21.22% | -26.78% | 1.004 | 0.792 | 0.59% | 657.16% |
| fundamental_strength_value_v1 | locked_test | -2.93% | -40.33% | -0.043 | -0.073 | -17.78% | 752.83% |
| fundamental_strength_value_v1 | full | 7.71% | -40.33% | 0.443 | 0.191 | 70.60% | 816.11% |
| quality_v1_baseline | validation | 19.64% | -24.41% | 0.942 | 0.805 | -5.93% | 435.06% |
| quality_v1_baseline | locked_test | -1.75% | -39.31% | 0.021 | -0.045 | -13.02% | 417.45% |
| quality_v1_baseline | full | 6.39% | -49.16% | 0.384 | 0.130 | 41.39% | 587.89% |

## 主策略年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 79.82% | -33.96% | 1.860 |
| 2016 | 20.18% | -12.49% | 0.894 |
| 2017 | -0.50% | -9.25% | 0.015 |
| 2018 | -26.14% | -30.79% | -1.149 |
| 2019 | 27.39% | -26.78% | 1.187 |
| 2020 | 5.67% | -14.64% | 0.351 |
| 2021 | 27.38% | -15.04% | 1.508 |
| 2022 | -14.30% | -22.50% | -0.559 |
| 2023 | -4.97% | -17.29% | -0.284 |
| 2024 | -2.46% | -27.96% | 0.044 |
| 2025 | 14.57% | -11.76% | 0.931 |
| 2026 | -10.75% | -16.66% | -0.568 |

## 固定晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- FAIL：locked_test_drawdown_within_30pct
- FAIL：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- FAIL：at_least_nine_positive_years
- FAIL：annual_turnover_below_8x

结论：终止，不注册生产策略。
