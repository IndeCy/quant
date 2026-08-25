# Trend Filtered Reversal V1 Study

- 数据截止：20260723
- 固定主策略：20日回撤介于0%与-20%，且120日收益为正、收盘价高于MA120、MA60高于MA120。
- 因子：20日回撤越深分数越高；Top40等权，月频调仓。
- 归因对照：相同回撤范围但不做长期趋势过滤，不参与参数选择。
- 统一口径：全A上市满3年、剔除ST/退市/停牌/成交额最低20%，qfq、M0 T+1、5bps及原风险层。
- 与无趋势过滤反转日收益相关性：0.908。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| unfiltered_short_reversal_v1 | validation | 8.33% | -33.84% | 0.438 | 0.246 | -47.96% | 2380.54% |
| unfiltered_short_reversal_v1 | locked_test | -10.40% | -49.21% | -0.283 | -0.211 | -44.21% | 2321.10% |
| unfiltered_short_reversal_v1 | full | -4.49% | -74.72% | -0.028 | -0.060 | -98.81% | 2440.85% |
| trend_filtered_reversal_v1 | validation | 15.66% | -28.48% | 0.682 | 0.550 | -21.64% | 2386.50% |
| trend_filtered_reversal_v1 | locked_test | -16.57% | -61.57% | -0.534 | -0.269 | -60.79% | 2398.93% |
| trend_filtered_reversal_v1 | full | -3.79% | -72.51% | -0.002 | -0.052 | -93.71% | 2389.89% |

## 主策略年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 95.46% | -33.96% | 2.014 |
| 2016 | 9.87% | -13.58% | 0.482 |
| 2017 | -24.32% | -29.70% | -1.267 |
| 2018 | -37.64% | -38.56% | -1.662 |
| 2019 | 41.44% | -18.59% | 1.422 |
| 2020 | 4.10% | -20.77% | 0.285 |
| 2021 | 1.64% | -17.61% | 0.186 |
| 2022 | -37.55% | -40.59% | -1.527 |
| 2023 | -3.00% | -23.79% | -0.036 |
| 2024 | -22.64% | -39.87% | -0.675 |
| 2025 | 1.02% | -23.92% | 0.175 |
| 2026 | -17.19% | -28.23% | -0.574 |

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
