# 业绩预告 × Quality 确认 V1

- 数据截止：20260724。
- 信号：正向业绩预告强度与年度 Quality 分数横截面秩各 50%。
- 组合：标准股票池交集、Top40、月频等权，不增加因子。
- 执行：M0 T+1、qfq、5bps；三条曲线统一使用
  `GRID(20日组合波动率>45%时仓位30%，否则100%)`。
- 研究约束：参数和门槛在收益扫描前冻结，不做后续变体。
- 候选平均仓位/降仓日/切换次数：
  96.7% /
  132 /
  53。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| forecast_quality_confirmation_v1 | 2015_2017 | 10.17% | -44.53% | 0.485 | 0.228 | 17.15% | 13.96x |
| forecast_quality_confirmation_v1 | 2018_2020 | 10.51% | -32.58% | 0.520 | 0.323 | -0.17% | 9.43x |
| forecast_quality_confirmation_v1 | 2021_2023 | -15.77% | -51.01% | -0.705 | -0.309 | -7.61% | 10.31x |
| forecast_quality_confirmation_v1 | 2024_latest | 19.87% | -19.87% | 0.839 | 1.000 | 10.13% | 11.26x |
| forecast_quality_confirmation_v1 | full | 5.22% | -58.20% | 0.328 | 0.090 | 20.36% | 11.23x |
| forecast_only_grid_control | 2015_2017 | 23.14% | -36.79% | 0.872 | 0.629 | 67.75% | 13.53x |
| forecast_only_grid_control | 2018_2020 | -1.01% | -32.64% | 0.092 | -0.031 | -36.65% | 11.31x |
| forecast_only_grid_control | 2021_2023 | -8.16% | -42.77% | -0.253 | -0.191 | 9.68% | 8.99x |
| forecast_only_grid_control | 2024_latest | 28.94% | -19.41% | 1.079 | 1.491 | 40.77% | 11.99x |
| forecast_only_grid_control | full | 9.54% | -51.47% | 0.479 | 0.185 | 120.05% | 11.45x |
| quality_only_grid_control | 2015_2017 | 20.12% | -33.79% | 0.828 | 0.596 | 55.02% | 10.28x |
| quality_only_grid_control | 2018_2020 | 13.28% | -26.75% | 0.705 | 0.496 | 9.75% | 4.23x |
| quality_only_grid_control | 2021_2023 | -2.76% | -30.38% | -0.068 | -0.091 | 23.70% | 4.40x |
| quality_only_grid_control | 2024_latest | 19.97% | -19.31% | 0.917 | 1.034 | 10.44% | 5.80x |
| quality_only_grid_control | full | 12.20% | -33.79% | 0.632 | 0.361 | 204.59% | 5.88x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 67.92% | -39.63% | 1.615 |
| 2016 | -12.31% | -22.77% | -0.340 |
| 2017 | -2.90% | -15.05% | -0.088 |
| 2018 | -29.99% | -32.08% | -1.264 |
| 2019 | 40.27% | -18.67% | 1.580 |
| 2020 | 36.60% | -15.18% | 1.279 |
| 2021 | -0.87% | -18.64% | 0.064 |
| 2022 | -25.10% | -27.57% | -0.976 |
| 2023 | -20.62% | -29.99% | -1.513 |
| 2024 | 13.14% | -19.87% | 0.585 |
| 2025 | 33.55% | -17.61% | 1.441 |
| 2026 | 8.61% | -14.81% | 0.437 |

## 相对预告单腿

- 回撤改善：-6.73%。
- Sharpe 变化：-0.151。
- 年化收益变化：-4.32%。

## 固定门槛

- FAIL：full_annual_return_at_least_10pct
- FAIL：full_drawdown_within_30pct
- FAIL：full_sharpe_at_least_065
- PASS：full_positive_excess
- PASS：at_least_three_positive_folds
- FAIL：worst_fold_drawdown_within_30pct
- PASS：median_fold_sharpe_at_least_035
- FAIL：annual_turnover_below_10x
- FAIL：forecast_drawdown_improves_10pct
- FAIL：forecast_sharpe_improves
- FAIL：forecast_return_loss_within_2pct

结论：未通过，保留失败指纹且不注册生产策略。
