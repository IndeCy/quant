# 黄金国债等权防守策略鲁棒性 V1

- 数据截止：20260724。
- 主策略始终固定为黄金50%+5年国债50%，月频恢复等权。
- 10/20bps与季度再平衡只做压力测试，不用于反向选择参数。
- 黄金与国债日收益相关性：0.105。
- 正收益滚动三年窗口：
  100.0%。

| 场景 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
| gold_bond_monthly_5bps | 7.18% | -16.58% | 0.921 | 0.26x |
| gold_bond_monthly_10bps | 7.17% | -16.60% | 0.919 | 0.25x |
| gold_bond_monthly_20bps | 7.14% | -16.61% | 0.916 | 0.25x |
| gold_bond_quarterly_5bps | 7.62% | -16.47% | 0.965 | 0.17x |
| gold_only_monthly_control | 11.15% | -30.52% | 0.772 | 0.06x |
| bond_only_monthly_control | 2.94% | -4.92% | 1.285 | 0.08x |

## 滚动三年

| 窗口 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| 2015_2017 | 1.83% | -7.44% | 0.309 |
| 2016_2018 | 5.25% | -7.44% | 0.926 |
| 2017_2019 | 5.98% | -4.79% | 1.143 |
| 2018_2020 | 8.20% | -9.22% | 1.108 |
| 2019_2021 | 6.15% | -10.53% | 0.796 |
| 2020_2022 | 4.52% | -10.53% | 0.617 |
| 2021_2023 | 4.90% | -5.64% | 0.862 |
| 2022_2024 | 11.16% | -5.41% | 1.783 |
| 2023_2025 | 18.08% | -6.06% | 2.249 |
| 2024_2026 | 14.98% | -16.58% | 1.296 |

## 与 Quality 相关性

| 区间 | 日收益相关性 |
|---|---:|
| 2015_2017 | -0.037 |
| 2018_2020 | -0.062 |
| 2021_2023 | -0.000 |
| 2024_latest | 0.224 |
| full | 0.047 |

## 最大回撤归因

- 组合峰值/谷底：20260129 / 20260701。
- 组合区间跌幅：-16.58%。
- 黄金同期：-30.52%。
- 国债同期：1.16%。

## 固定门槛

- PASS：stress20_annual_return_at_least_5pct
- PASS：stress20_drawdown_within_20pct
- PASS：stress20_sharpe_at_least_075
- PASS：quarterly_return_difference_within_1pct
- PASS：quarterly_drawdown_deterioration_within_3pct
- PASS：quarterly_sharpe_at_least_070
- PASS：rolling_positive_share_at_least_75pct
- PASS：rolling_worst_drawdown_within_20pct
- PASS：all_fold_quality_correlations_within_030
- PASS：gold_bond_correlation_within_040
- PASS：bond_full_return_positive

结论：具备进入长期前瞻Paper条件。
