# Quality 盈利底线过滤 V1

- 数据截止：20260724。
- 原 Quality 80% + E/P 10% + B/P 10% 分数、Top20和月频不变。
- 仅剔除最近五个连续年报中最低 ROA 不大于 0 的公司。
- 先在完整基线截面评分，再过滤，盈利底线不参与加权。
- 候选与基线统一使用 M0 T+1、qfq、5bps 和
  `GRID(20日波动率>45%时仓位30%)`。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quality_profitability_floor_filter_v1 | 2015_2017 | 24.81% | -25.41% | 1.038 | 0.977 | 75.05% | 10.36x |
| quality_profitability_floor_filter_v1 | 2018_2020 | 5.86% | -25.11% | 0.386 | 0.233 | -15.80% | 5.88x |
| quality_profitability_floor_filter_v1 | 2021_2023 | 3.61% | -21.04% | 0.289 | 0.172 | 42.22% | 5.51x |
| quality_profitability_floor_filter_v1 | 2024_latest | 16.07% | -18.32% | 0.841 | 0.877 | -1.74% | 6.38x |
| quality_profitability_floor_filter_v1 | full | 12.51% | -25.41% | 0.674 | 0.492 | 215.96% | 6.79x |
| quality_balanced_value_same_run_control | 2015_2017 | 24.96% | -25.46% | 1.042 | 0.980 | 75.70% | 10.45x |
| quality_balanced_value_same_run_control | 2018_2020 | 3.67% | -24.56% | 0.281 | 0.150 | -22.73% | 5.69x |
| quality_balanced_value_same_run_control | 2021_2023 | 5.34% | -24.84% | 0.376 | 0.215 | 47.64% | 5.82x |
| quality_balanced_value_same_run_control | 2024_latest | 18.01% | -19.48% | 0.899 | 0.924 | 4.25% | 6.71x |
| quality_balanced_value_same_run_control | full | 12.85% | -25.46% | 0.682 | 0.504 | 228.53% | 6.97x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 68.39% | -24.38% | 1.736 |
| 2016 | 12.60% | -14.08% | 0.669 |
| 2017 | 9.93% | -11.88% | 0.839 |
| 2018 | -21.09% | -25.11% | -1.137 |
| 2019 | 29.73% | -18.52% | 1.511 |
| 2020 | 16.30% | -14.78% | 0.800 |
| 2021 | 13.41% | -17.03% | 0.824 |
| 2022 | -17.18% | -21.04% | -0.751 |
| 2023 | 14.11% | -7.43% | 1.104 |
| 2024 | 24.64% | -17.54% | 1.023 |
| 2025 | 5.75% | -11.09% | 0.446 |
| 2026 | 27.40% | -12.91% | 1.375 |

## 相对原 Quality

- 全样本回撤改善：0.06%。
- 2015–2017 回撤改善：0.06%。
- Sharpe 变化：-0.008。
- 年化收益变化：-0.34%。

## 固定门槛

- PASS：full_annual_return_at_least_10pct
- PASS：full_drawdown_within_30pct
- PASS：full_sharpe_at_least_065
- PASS：full_calmar_at_least_040
- PASS：full_positive_excess
- PASS：at_least_three_positive_folds
- PASS：worst_fold_drawdown_within_30pct
- PASS：median_fold_sharpe_at_least_035
- PASS：annual_turnover_below_8x
- FAIL：full_drawdown_improves_3pct
- FAIL：early_drawdown_improves_3pct
- FAIL：baseline_sharpe_not_worse
- PASS：baseline_return_loss_within_1_5pct

结论：终止并保留失败指纹，不注册生产。
