# A股科技ETF周频5日反转 V1

- 固定四只流动性合格科技ETF；周末按过去5日收益从弱到强排名。
- 持有最弱两只、各50%；下一交易日M0执行，基础10bps、压力30bps。
- 不做窗口、Top-N、权重或频率网格。
- 数据共同截止：20260728。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2020_2021 | 23.53% | -25.15% | 0.867 | 0.936 | 55.81x |
| 2022_2023 | -21.57% | -40.43% | -0.765 | -0.534 | 50.75x |
| 2024_latest | 13.39% | -28.30% | 0.530 | 0.473 | 47.30x |
| locked_test | 13.39% | -28.30% | 0.530 | 0.473 | 47.30x |
| full | 3.67% | -54.81% | 0.272 | 0.067 | 51.25x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| a_share_tech_etf_weekly_5d_reversal_v1 | 3.67% | -54.81% | 0.272 |
| tech_etf_weekly_5d_momentum_mirror_control | 8.16% | -67.98% | 0.401 |
| tech_etf_liquid_four_equal_control | 13.36% | -49.56% | 0.556 |
| hs300_direct_tech_reversal_control | 3.66% | -42.12% | 0.283 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2020 | 27.48% | -25.15% | 0.867 |
| 2021 | 18.06% | -17.90% | 0.866 |
| 2022 | -34.06% | -39.26% | -1.325 |
| 2023 | -7.78% | -32.01% | -0.190 |
| 2024 | 7.84% | -23.37% | 0.388 |
| 2025 | 36.51% | -25.43% | 1.166 |
| 2026 | -6.01% | -27.06% | 0.076 |

## 最新目标

| 代码 | 名称 | 权重 | 信号日5日收益 |
|---|---|---:|---:|
| 515880.SH | 通信ETF | 50.0% | -14.41% |
| 515000.SH | 科技龙头ETF | 50.0% | -10.43% |

## 选择覆盖

| 代码 | 名称 | 入选占比 |
|---|---|---:|
| 512480.SH | 半导体ETF | 24.5% |
| 515880.SH | 通信ETF | 23.1% |
| 512720.SH | 计算机ETF | 26.3% |
| 515000.SH | 科技龙头ETF | 26.1% |

- 年化波动：31.39%
- 最差单日：-10.13%
- 95% Expected Shortfall：-4.38%
- 与Quality日收益相关性：0.468

## 冻结门槛

- PASS：data_audit
- FAIL：full_return_at_least_8pct
- FAIL：full_drawdown_within_50pct
- FAIL：full_sharpe_at_least_045
- FAIL：full_calmar_at_least_015
- FAIL：return_lift_vs_equal_at_least_1pct
- FAIL：sharpe_lift_vs_equal_at_least_005
- FAIL：return_lift_vs_momentum_at_least_2pct
- PASS：positive_excess_vs_hs300
- PASS：at_least_two_positive_folds
- PASS：worst_fold_drawdown_within_55pct
- PASS：median_fold_sharpe_at_least_035
- PASS：locked_return_at_least_8pct
- PASS：locked_drawdown_within_40pct
- PASS：locked_sharpe_at_least_050
- PASS：at_least_four_positive_years
- FAIL：annual_turnover_below_30x
- FAIL：stress_return_at_least_6pct
- FAIL：stress_sharpe_at_least_035
- FAIL：worst_day_within_10pct
- FAIL：expected_shortfall_95_within_4pct
- PASS：quality_correlation_at_most_080
- PASS：selection_share_between_10_and_45pct

结论：未通过冻结门槛，归档且不注册。
