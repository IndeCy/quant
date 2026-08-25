# A股科技ETF周频相对强度轮动 V1

- 数据共同截止：20260728。
- 固定池：半导体、通信、计算机、人工智能、科技龙头ETF。
- 每周最后一个交易日计算20日相对强度；只允许正动量且站上MA60的ETF入选。
- 前两名各40%，固定20%五年国债；空余槽位全部回到国债。
- 信号下一交易日经M0执行，统一qfq、10bps，ETF免印花税。
- 不做窗口、TopN、权重或调仓频率网格。
- 与Quality日收益相关性：0.252。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2020_2021 | 9.78% | -25.55% | 0.547 | 0.383 | 28.01x |
| 2022_2023 | -10.05% | -22.55% | -0.612 | -0.446 | 22.95x |
| 2024_latest | 28.20% | -20.69% | 1.090 | 1.363 | 21.37x |
| locked_test | 28.20% | -20.69% | 1.090 | 1.363 | 21.37x |
| full | 9.80% | -33.92% | 0.539 | 0.289 | 23.79x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| a_share_tech_etf_weekly_relative_strength_v1 | 9.80% | -33.92% | 0.539 | 0.289 |
| tech_etf_equal_weekly_control | 13.69% | -48.91% | 0.565 | 0.280 |
| semiconductor_direct_control | 17.54% | -62.49% | 0.611 | 0.281 |
| hs300_direct_tech_control | 3.66% | -42.12% | 0.283 | 0.087 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2020 | 15.25% | -19.92% | 0.690 |
| 2021 | 4.08% | -15.93% | 0.329 |
| 2022 | -14.68% | -15.93% | -1.343 |
| 2023 | -5.15% | -22.55% | -0.192 |
| 2024 | 8.54% | -15.30% | 0.485 |
| 2025 | 55.45% | -13.91% | 1.894 |
| 2026 | 24.13% | -20.69% | 0.826 |

## 最新目标

| 代码 | 资产 | 权重 | 角色 |
|---|---|---:|---|
| 511010.SH | 5年国债ETF | 100.0% | DEFENSIVE |

## 尾部与状态

- 年化波动：21.71%
- 最差单日：-7.80%
- 95% Expected Shortfall：-3.34%
- 最长水下期：1330个交易日
- 平均风险资产目标仓位：43.1%

## 冻结门槛

- PASS：data_audit
- PASS：full_return_at_least_8pct
- FAIL：full_drawdown_within_30pct
- FAIL：full_sharpe_at_least_055
- PASS：full_calmar_at_least_025
- PASS：positive_excess_vs_hs300
- FAIL：return_lift_vs_equal_nonnegative
- PASS：drawdown_improvement_vs_equal_at_least_5pct
- FAIL：sharpe_lift_vs_equal_at_least_010
- FAIL：all_three_folds_positive
- PASS：worst_fold_drawdown_within_35pct
- PASS：median_fold_sharpe_at_least_040
- PASS：locked_return_at_least_6pct
- PASS：locked_drawdown_within_28pct
- PASS：locked_sharpe_at_least_045
- FAIL：annual_turnover_below_12x
- PASS：at_least_four_positive_years
- FAIL：stress_return_at_least_7pct
- FAIL：stress_sharpe_at_least_050
- PASS：worst_day_within_9pct
- PASS：expected_shortfall_95_within_35pct
- PASS：quality_correlation_at_most_075

结论：未通过冻结门槛，归档且不注册。
