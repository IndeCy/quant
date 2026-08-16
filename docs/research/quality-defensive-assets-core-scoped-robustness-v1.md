# Quality防守袖套鲁棒性确认 V1

- 数据截止：20260617。
- 主方案固定为Quality 70%、黄金15%、国债15%，风险层仅管理Quality核心。
- 本研究不选择表现最好的场景，只用相邻权重和执行压力测试淘汰主方案。
- 所有场景保持qfq、财务as-of、M0和T+1。

## 场景结果

| 场景 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| 基准70/15/15 | 12.06% | -17.70% | 0.835 | 0.681 | 187.04% | 5.09x |
| 相邻60/20/20 | 11.62% | -15.39% | 0.904 | 0.755 | 172.13% | 4.42x |
| 相邻80/10/10 | 12.46% | -20.27% | 0.779 | 0.615 | 201.24% | 5.74x |
| 黄金单袖套70/30 | 13.56% | -18.51% | 0.894 | 0.733 | 242.86% | 5.05x |
| 国债单袖套70/30 | 10.56% | -17.36% | 0.759 | 0.609 | 138.56% | 5.09x |
| 滑点10bps | 11.74% | -18.02% | 0.817 | 0.652 | 176.23% | 5.09x |
| 滑点20bps | 11.13% | -18.60% | 0.780 | 0.598 | 156.05% | 5.10x |
| 风险信号额外延迟1天 | 11.24% | -22.66% | 0.786 | 0.496 | 159.68% | 5.11x |

## 主方案分段

| 阶段 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| 2015_2017 | 18.57% | -17.70% | 1.081 |
| 2018_2020 | 5.54% | -17.31% | 0.454 |
| 2021_2023 | 5.69% | -16.84% | 0.495 |
| 2024_latest | 19.34% | -13.49% | 1.213 |
| full | 12.06% | -17.70% | 0.835 |

## 冻结门槛

- PASS：baseline_annual_return_at_least_10pct
- PASS：baseline_drawdown_within_25pct
- PASS：baseline_sharpe_at_least_065
- PASS：baseline_calmar_at_least_040
- PASS：baseline_positive_excess
- PASS：all_baseline_folds_positive
- PASS：at_least_nine_positive_years
- PASS：neighbor_weights_form_platform
- PASS：execution_cost_stress_survives
- PASS：one_day_extra_delay_survives
- PASS：single_defensive_assets_survive
- PASS：all_scenarios_turnover_below_8x

- 全场景最低年化：10.56%。
- 全场景最差回撤：-22.66%。
- 全场景最低Sharpe：0.759。

结论：通过鲁棒性确认，可进入长期Paper观察。
