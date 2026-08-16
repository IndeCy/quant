# 纳指趋势驱动黄金国债切换 V1

- 数据共同截止：20260728。
- 月末纳指ETF MA20 > MA200 时持有纳指60%/黄金40%；
  否则切换为黄金50%/5年国债50%。
- 信号下一交易日经M0执行，统一qfq、5bps、ETF免印花税。
- 直接机会成本：静态纳指/黄金60/40与场内标普500ETF。
- 不做权重、窗口或调仓频率网格。
- 与Quality日收益相关性：0.185。
- 最新状态：进攻，
  MA20=1.649，MA200=1.422。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2019_2021 | 14.43% | -21.71% | 0.921 | 0.665 | 1.64x |
| 2022_2024 | 19.35% | -10.92% | 1.559 | 1.772 | 0.89x |
| 2025_latest | 8.69% | -17.16% | 0.555 | 0.506 | 3.37x |
| locked_test | 15.85% | -17.16% | 1.107 | 0.924 | 2.03x |
| oos_full | 15.29% | -21.71% | 1.027 | 0.705 | 1.92x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| nasdaq_trend_gold_bond_switch_v1 | 15.29% | -21.71% | 1.027 | 0.705 |
| nasdaq_gold_static_60_40_control | 20.01% | -21.71% | 1.171 | 0.922 |
| sp500_direct_switch_control | 15.96% | -29.67% | 0.890 | 0.538 |
| nasdaq_direct_switch_control | 21.25% | -31.10% | 0.905 | 0.683 |

## 状态归因

| 状态 | 交易日 | 时间占比 | 状态年化 | 日胜率 |
|---|---:|---:|---:|---:|
| GOLD_BOND_DEFENSIVE | 381 | 21.0% | 7.07% | 53.8% |
| NASDAQ_GOLD_ACTIVE | 1431 | 79.0% | 17.85% | 56.4% |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2019 | 15.97% | -6.69% | 1.747 |
| 2020 | 13.90% | -21.71% | 0.672 |
| 2021 | 12.85% | -8.26% | 1.068 |
| 2022 | -4.99% | -10.36% | -0.541 |
| 2023 | 33.54% | -4.85% | 2.922 |
| 2024 | 33.92% | -10.92% | 1.981 |
| 2025 | 24.18% | -8.35% | 1.700 |
| 2026 | -16.77% | -17.16% | -0.646 |

## 尾部诊断

- 年化波动：14.97%
- 最差单日：-6.24%
- 95% Expected Shortfall：-2.36%
- 最长水下期：621个交易日

## 冻结门槛

- PASS：data_audit
- PASS：oos_return_at_least_12pct
- FAIL：oos_drawdown_within_20pct
- PASS：oos_sharpe_at_least_100
- PASS：oos_calmar_at_least_060
- FAIL：return_lift_vs_sp500_at_least_05pct
- PASS：sharpe_lift_vs_sp500_at_least_010
- FAIL：return_shortfall_vs_static_within_4pct
- FAIL：drawdown_improvement_vs_static_at_least_2pct
- PASS：all_three_folds_positive
- PASS：worst_fold_drawdown_within_22pct
- PASS：median_fold_sharpe_at_least_075
- PASS：locked_return_at_least_10pct
- PASS：locked_drawdown_within_20pct
- PASS：locked_sharpe_at_least_085
- PASS：at_least_six_positive_years
- PASS：annual_turnover_below_2x
- PASS：stress_return_at_least_11pct
- PASS：stress_sharpe_at_least_090
- PASS：worst_day_within_8pct
- PASS：expected_shortfall_95_within_25pct
- PASS：quality_correlation_at_most_050
- PASS：active_day_share_between_35_and_85pct

结论：未通过冻结门槛，归档且不注册。
