# Quality防守袖套 Paper 可执行性 V1

- 数据截止：20260617，初始资金100万元。
- 基准Paper：T+1、10bps、成交量参与率1%、万三佣金、最低5元。
- 压力Paper：T+2、20bps、成交量参与率0.2%，其余费用相同。
- 股票卖出收千一印花税，黄金与国债ETF免印花税，全部100股整手。
- 部分成交剩余数量不自动追单，作为保守执行压力。

## 收益与风险

| 口径 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 | 总执行成本 |
|---|---:|---:|---:|---:|---:|---:|
| M0基准 | 12.06% | -17.70% | 0.835 | 0.681 | 5.09x | 149,058 |
| Paper基准 | 11.74% | -18.02% | 0.817 | 0.651 | 5.09x | 200,696 |
| Paper压力 | 10.93% | -23.01% | 0.772 | 0.475 | 4.89x | 280,648 |

## 执行偏差

| 场景 | 填单率 | 拒单率 | 部分成交率 | 平均持仓漂移 | 最大漂移 | 跟踪误差 |
|---|---:|---:|---:|---:|---:|---:|
| Paper基准 | 91.79% | 6.57% | 1.77% | 5.65% | 140.54% | 0.12% |
| Paper压力 | 85.85% | 6.84% | 8.18% | 9.55% | 141.35% | 2.21% |

## 冻结门槛

- PASS：baseline_return_within_2pct_of_m0
- PASS：baseline_drawdown_within_3pct_of_m0
- PASS：baseline_sharpe_within_010_of_m0
- PASS：baseline_tracking_error_below_5pct
- FAIL：baseline_fill_rate_at_least_98pct
- FAIL：baseline_rejection_rate_below_5pct
- PASS：baseline_partial_orders_below_20pct
- FAIL：baseline_average_drift_below_5pct
- PASS：baseline_cost_below_25pct_initial_cash
- PASS：stress_annual_return_at_least_9pct
- PASS：stress_drawdown_within_25pct
- PASS：stress_sharpe_at_least_060
- PASS：stress_tracking_error_below_8pct
- FAIL：stress_fill_rate_at_least_90pct
- PASS：stress_rejection_rate_below_10pct
- PASS：stress_average_drift_below_10pct

结论：执行偏差不可接受，不注册Paper。
