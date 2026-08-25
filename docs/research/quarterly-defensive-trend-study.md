# Quarterly Defensive Trend V1 Study

- 数据截止：20260723
- 固定主策略：正中期动量池内选择60日低波Top40，季度等权换股。
- 风险层：组合20日波动率超过45%或510300 MA120不高于MA250时，仓位上限30%。
- 归因对照：相同季度持仓只使用组合波动率风险层，不参与参数选择。
- 统一口径：全A上市满3年、剔除ST/退市/停牌/成交额最低20%，qfq、M0 T+1和5bps。
- 与无市场趋势控制版本日收益相关性：0.870。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quarterly_positive_momentum_lowvol_v1 | validation | 14.54% | -16.95% | 0.982 | 0.858 | -25.88% | 653.15% |
| quarterly_positive_momentum_lowvol_v1 | locked_test | 10.34% | -13.15% | 0.761 | 0.786 | 47.72% | 644.83% |
| quarterly_positive_momentum_lowvol_v1 | full | 7.44% | -44.23% | 0.509 | 0.168 | 63.69% | 674.64% |
| quarterly_defensive_trend_v1 | validation | 10.40% | -13.45% | 0.811 | 0.773 | -40.84% | 593.52% |
| quarterly_defensive_trend_v1 | locked_test | 6.86% | -13.12% | 0.676 | 0.523 | 27.60% | 478.95% |
| quarterly_defensive_trend_v1 | full | 6.19% | -41.42% | 0.495 | 0.149 | 36.39% | 518.21% |

## 主策略年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 42.28% | -41.42% | 1.253 |
| 2016 | 1.08% | -5.49% | 0.198 |
| 2017 | 12.22% | -6.98% | 1.517 |
| 2018 | -31.34% | -34.58% | -3.870 |
| 2019 | 7.90% | -5.65% | 0.859 |
| 2020 | 8.19% | -13.45% | 0.524 |
| 2021 | 15.07% | -6.47% | 1.395 |
| 2022 | -1.21% | -3.54% | -0.232 |
| 2023 | 6.70% | -7.14% | 0.997 |
| 2024 | 20.73% | -8.42% | 1.513 |
| 2025 | 6.96% | -7.59% | 0.603 |
| 2026 | 1.64% | -13.12% | 0.185 |

## 固定晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- PASS：locked_test_sharpe_at_least_055
- PASS：locked_test_drawdown_within_30pct
- PASS：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- PASS：at_least_nine_positive_years
- PASS：annual_turnover_below_8x

结论：终止，不注册生产策略。
