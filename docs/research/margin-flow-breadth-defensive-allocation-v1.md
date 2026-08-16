# 融资净买入广度防守配置 V1

- 广度≥50%：沪深300/黄金/国债=60/20/20；否则黄金/国债=50/50。
- 月末T-1可见信号，T+1开盘，5bps；20bps压力；无参数搜索。
- 风险状态占比：39.86%；切换：49次。
- 与Quality日收益相关性：0.418。

| 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
| 2015_2017 | 10.46% | -22.83% | 0.792 | 6.69x |
| 2018_2020 | 7.59% | -11.29% | 0.767 | 3.96x |
| 2021_2023 | -3.89% | -13.51% | -0.551 | 5.06x |
| 2024_latest | 8.83% | -12.97% | 0.779 | 6.58x |
| locked_test | 8.83% | -12.97% | 0.779 | 6.58x |
| full | 5.53% | -22.83% | 0.548 | 5.51x |

## 全期对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| margin_flow_breadth_defensive_allocation_v1 | 5.53% | -22.83% | 0.548 |
| margin_breadth_static_equal_control | 7.14% | -16.20% | 0.798 |
| margin_breadth_hs300_direct_control | 4.99% | -45.43% | 0.331 |

## 冻结门槛

- FAIL `full_return_at_least_7pct`
- FAIL `full_drawdown_within_20pct`
- FAIL `full_sharpe_at_least_090`
- FAIL `full_calmar_at_least_035`
- PASS `positive_excess_vs_hs300`
- FAIL `return_lift_vs_static_at_least_05pct`
- FAIL `sharpe_lift_vs_static_at_least_010`
- PASS `at_least_three_positive_folds`
- FAIL `worst_fold_drawdown_within_22pct`
- PASS `median_fold_sharpe_at_least_060`
- PASS `locked_return_at_least_8pct`
- PASS `locked_drawdown_within_18pct`
- PASS `locked_sharpe_at_least_075`
- FAIL `annual_turnover_below_3x`
- FAIL `stress_return_at_least_65pct`
- FAIL `stress_sharpe_at_least_080`
- PASS `quality_correlation_at_most_050`

结论：未通过研究门槛，归档且不注册。
