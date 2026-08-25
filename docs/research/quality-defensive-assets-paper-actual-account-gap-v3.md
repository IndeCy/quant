# Quality防守袖套 Paper 实际账户差异 V3

- 数据截止：20260617，策略与V1/V2完全相同。
- V1记录绝对成交约束，V2记录相对理想目标的漂移，两个失败结论均保留。
- V3只回答Paper实际账户相对M0实际账户增加了多少持仓和净值偏差。

## 收益风险

| 口径 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| M0 | 12.06% | -17.70% | 0.835 | 0.681 |
| Paper基准 | 11.74% | -18.02% | 0.817 | 0.651 |
| Paper压力 | 10.93% | -23.01% | 0.772 | 0.475 |

## 实际账户增量偏差

| 场景 | Paper/M0成功单 | 新增拒单率 | 平均持仓差 | 最大持仓差 | 最新持仓差 | 跟踪误差 |
|---|---:|---:|---:|---:|---:|---:|
| Paper基准 | 99.84% | 0.00% | 1.75% | 4.15% | 3.11% | 0.12% |
| Paper压力 | 101.76% | 0.23% | 11.77% | 54.05% | 11.53% | 2.21% |

## 冻结门槛

- PASS：baseline_return_within_2pct_of_m0
- PASS：baseline_drawdown_within_3pct_of_m0
- PASS：baseline_sharpe_within_010_of_m0
- PASS：baseline_tracking_error_below_5pct
- PASS：baseline_success_orders_at_least_98pct_of_m0
- PASS：baseline_incremental_rejections_below_2pct
- PASS：baseline_actual_position_gap_below_5pct
- PASS：baseline_latest_actual_gap_below_5pct
- PASS：stress_annual_return_at_least_9pct
- PASS：stress_drawdown_within_25pct
- PASS：stress_sharpe_at_least_060
- PASS：stress_tracking_error_below_8pct
- PASS：stress_success_orders_at_least_95pct_of_m0
- PASS：stress_incremental_rejections_below_5pct
- FAIL：stress_actual_position_gap_below_10pct
- FAIL：stress_latest_actual_gap_below_10pct

结论：Paper实际账户仍显著偏离M0。
