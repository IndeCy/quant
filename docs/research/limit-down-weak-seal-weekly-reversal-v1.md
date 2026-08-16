# 跌停弱封单周频反转 V1

- 区间：20230101 至 20260615
- 每周末从近五日非ST跌停池按剩余封单/成交额由低到高选20只，次周开盘等权。
- 开盘时点 M0、10bps；30bps压力测试；参数未做搜索。

| 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
| 2023 | -43.87% | -45.91% | -2.185 | 83.4x |
| 2024 | -53.85% | -52.77% | -2.588 | 58.7x |
| 2025_latest | -10.37% | -18.73% | -0.822 | 31.1x |
| locked_test | -10.37% | -18.73% | -0.822 | 31.1x |
| full | -35.64% | -77.43% | -1.898 | 66.7x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2023 | -43.87% | -45.91% | -2.185 |
| 2024 | -53.85% | -52.77% | -2.588 |
| 2025 | -9.01% | -18.73% | -0.656 |
| 2026 | -12.15% | -9.20% | -1.178 |

## 执行诊断

- 成交/失败：3553 / 2084
- 失败率：36.97%
- 失败原因：`{"limit_up": 4, "limit_down": 22, "missing_bar": 865, "cash_insufficient": 1193}`
- 最差单日/ES95：-7.39% / -3.67%
- 与 Quality 相关性：0.382

## 冻结门槛

- FAIL `full_return_at_least_8pct`
- FAIL `full_drawdown_within_35pct`
- FAIL `full_sharpe_at_least_055`
- FAIL `positive_excess_vs_hs300`
- PASS `return_lift_vs_amount_control_at_least_2pct`
- FAIL `sharpe_lift_vs_amount_control_at_least_010`
- FAIL `at_least_two_positive_folds`
- FAIL `worst_fold_drawdown_within_35pct`
- FAIL `median_fold_sharpe_at_least_040`
- FAIL `locked_return_at_least_8pct`
- PASS `locked_drawdown_within_30pct`
- FAIL `locked_sharpe_at_least_055`
- PASS `annual_turnover_below_70x`
- FAIL `stress_return_at_least_5pct`
- FAIL `stress_sharpe_at_least_040`
- FAIL `failed_order_rate_at_most_20pct`
- PASS `worst_day_within_12pct`
- PASS `expected_shortfall_95_within_6pct`
- PASS `quality_correlation_at_most_050`

结论：未通过研究门槛，归档且不注册。
