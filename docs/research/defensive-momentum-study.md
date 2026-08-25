# Defensive Momentum V1 Study

- 数据截止：20260722
- 固定主策略：120日至20日前动量50% + 60日低波50%，只保留正中期动量，Top40等权。
- 归因对照：跳过近月动量单腿、低波单腿；它们不参与主策略选参。
- 统一口径：全A上市满3年、剔除ST/退市/停牌/成交额最低20%，qfq、M0 T+1、5bps及原风险层。
- 与正中期动量池内低波单腿相关性：0.558。
- 与动量单腿相关性：0.897。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| skip_month_momentum_only_v1 | validation | 10.13% | -37.24% | 0.467 | 0.272 | -41.81% | 1654.69% |
| skip_month_momentum_only_v1 | locked_test | -25.24% | -72.31% | -0.875 | -0.349 | -77.52% | 1377.49% |
| skip_month_momentum_only_v1 | full | -10.93% | -86.66% | -0.238 | -0.126 | -130.47% | 1572.47% |
| positive_momentum_low_volatility_only_v1 | validation | 22.72% | -15.34% | 1.456 | 1.481 | 6.90% | 1572.76% |
| positive_momentum_low_volatility_only_v1 | locked_test | 9.37% | -14.67% | 0.686 | 0.639 | 42.30% | 1415.25% |
| positive_momentum_low_volatility_only_v1 | full | 7.47% | -54.93% | 0.508 | 0.136 | 65.05% | 1499.05% |
| defensive_momentum_v1 | validation | 30.08% | -22.64% | 1.121 | 1.329 | 40.17% | 1529.54% |
| defensive_momentum_v1 | locked_test | -20.15% | -65.93% | -0.713 | -0.306 | -68.17% | 1614.13% |
| defensive_momentum_v1 | full | -4.67% | -71.72% | -0.050 | -0.065 | -99.34% | 1620.27% |

## 主策略年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 48.16% | -41.29% | 1.284 |
| 2016 | -0.49% | -16.52% | 0.104 |
| 2017 | -2.81% | -14.53% | -0.130 |
| 2018 | -44.15% | -45.90% | -2.640 |
| 2019 | 35.42% | -18.87% | 1.402 |
| 2020 | 36.29% | -22.64% | 1.229 |
| 2021 | 13.87% | -19.06% | 0.612 |
| 2022 | -34.90% | -36.93% | -1.356 |
| 2023 | -22.51% | -32.08% | -1.010 |
| 2024 | -27.07% | -35.49% | -0.986 |
| 2025 | 13.10% | -17.25% | 0.619 |
| 2026 | -26.97% | -24.86% | -0.954 |

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
