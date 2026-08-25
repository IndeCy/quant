# 全球核心 × 纳指黄金四资产50/50 V1

- 资产权重：159941.SZ 30.0% / 513500.SH 16.7% / 518880.SH 36.7% / 511010.SH 16.7%
- 月频恢复固定权重，T+1开盘，5bps；20bps压力；无权重网格。
- 纳指黄金 V3 袖套已通过研究门槛；本研究只判断两袖套组合层。
- 与Quality日收益相关性：0.279。

| 区间 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| 2016_2018 | 9.17% | -7.93% | 1.142 |
| 2019_2021 | 18.03% | -16.76% | 1.467 |
| 2022_2024 | 15.04% | -10.68% | 1.335 |
| 2025_latest | 22.51% | -15.09% | 1.348 |
| locked_test | 17.64% | -15.09% | 1.332 |
| full | 14.78% | -16.76% | 1.279 |

## 全期对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
| global_core_nasdaq_gold_four_asset_50_50_v1 | 14.78% | -16.76% | 1.279 |
| four_asset_global_defensive_control | 11.10% | -12.97% | 1.327 |
| four_asset_nasdaq_gold_control | 18.39% | -21.71% | 1.178 |
| four_asset_sp500_direct_control | 14.94% | -29.67% | 0.846 |

## 冻结门槛

- PASS `full_return_at_least_13pct`
- PASS `full_drawdown_within_20pct`
- PASS `full_sharpe_at_least_110`
- PASS `full_calmar_at_least_065`
- FAIL `return_lift_vs_sp500_at_least_05pct`
- PASS `sharpe_lift_vs_sp500_at_least_015`
- PASS `return_shortfall_vs_growth_within_5pct`
- PASS `drawdown_improvement_vs_growth_at_least_3pct`
- PASS `return_lift_vs_core_at_least_3pct`
- PASS `all_folds_positive`
- PASS `worst_fold_drawdown_within_22pct`
- PASS `median_fold_sharpe_at_least_080`
- PASS `locked_return_at_least_13pct`
- PASS `locked_drawdown_within_20pct`
- PASS `locked_sharpe_at_least_090`
- PASS `annual_turnover_below_1x`
- PASS `stress_return_at_least_125pct`
- PASS `stress_drawdown_within_21pct`
- PASS `stress_sharpe_at_least_100`
- PASS `quality_correlation_at_most_035`

结论：未通过研究门槛，归档且不改变底层袖套。
