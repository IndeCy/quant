# 涨跌停情绪防守配置 V1

- 情绪≥0.5：沪深300/黄金/国债 = 60/20/20；否则黄金/国债 = 50/50。
- 周末信号、T+1开盘、5bps；20bps压力；无阈值或权重搜索。
- 风险状态周占比：88.07%；切换次数：26。
- 与 Quality 日收益相关性：0.524。

| 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
| 2023 | -5.30% | -10.06% | -0.656 | 4.94x |
| 2024 | 15.79% | -6.45% | 1.171 | 12.57x |
| 2025_latest | 27.62% | -9.53% | 2.120 | 11.42x |
| locked_test | 27.62% | -9.53% | 2.120 | 11.42x |
| full | 13.62% | -12.80% | 1.182 | 10.24x |

## 全期对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| limit_event_sentiment_defensive_allocation_v1 | 13.62% | -12.80% | 1.182 |
| a_share_gold_bond_static_equal_control | 13.42% | -11.14% | 1.377 |
| hs300_direct_sentiment_control | 8.66% | -22.51% | 0.567 |

## 冻结门槛

- PASS `full_return_at_least_8pct`
- PASS `full_drawdown_within_25pct`
- PASS `full_sharpe_at_least_070`
- PASS `positive_excess_vs_hs300`
- FAIL `return_lift_vs_static_at_least_05pct`
- FAIL `sharpe_lift_vs_static_at_least_010`
- PASS `at_least_two_positive_folds`
- PASS `worst_fold_drawdown_within_25pct`
- PASS `median_fold_sharpe_at_least_050`
- PASS `locked_return_at_least_8pct`
- PASS `locked_drawdown_within_22pct`
- PASS `locked_sharpe_at_least_065`
- PASS `annual_turnover_below_15x`
- PASS `stress_return_at_least_7pct`
- PASS `stress_sharpe_at_least_060`
- FAIL `quality_correlation_at_most_050`

结论：未通过研究门槛，归档且不注册。
