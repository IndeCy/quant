# Quality防守袖套 Paper 增量偏差 V2

- 数据截止：20260617，策略和执行压力参数与V1完全相同。
- V1绝对拒单包含M0同样会拦截的停牌和涨跌停，并把T到T+1等待误计为漂移。
- V2不删除V1失败记录，只改用“Paper相对M0新增偏差”进行独立审计。

## 收益风险

| 口径 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| M0 | 12.06% | -17.70% | 0.835 | 0.681 | 5.09x |
| Paper基准 | 11.74% | -18.02% | 0.817 | 0.651 | 5.09x |
| Paper压力 | 10.93% | -23.01% | 0.772 | 0.475 | 4.89x |

## 增量执行差异

| 场景 | Paper/M0成功单 | 新增拒单率 | 成交后平均漂移 | 最新漂移 | 跟踪误差 | 绝对填单率 |
|---|---:|---:|---:|---:|---:|---:|
| Paper基准 | 99.84% | 0.00% | 6.09% | 0.00% | 0.12% | 91.79% |
| Paper压力 | 101.76% | 0.23% | 9.83% | 0.00% | 2.21% | 85.85% |

## 冻结门槛

- PASS：baseline_return_within_2pct_of_m0
- PASS：baseline_drawdown_within_3pct_of_m0
- PASS：baseline_sharpe_within_010_of_m0
- PASS：baseline_tracking_error_below_5pct
- PASS：baseline_success_orders_at_least_98pct_of_m0
- PASS：baseline_incremental_rejections_below_2pct
- FAIL：baseline_post_execution_drift_below_5pct
- PASS：baseline_latest_drift_below_5pct
- PASS：stress_annual_return_at_least_9pct
- PASS：stress_drawdown_within_25pct
- PASS：stress_sharpe_at_least_060
- PASS：stress_tracking_error_below_8pct
- PASS：stress_success_orders_at_least_95pct_of_m0
- PASS：stress_incremental_rejections_below_5pct
- PASS：stress_post_execution_drift_below_10pct
- PASS：stress_latest_drift_below_10pct

结论：仍存在不可接受的增量执行偏差。
