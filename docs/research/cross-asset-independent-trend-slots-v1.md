# 五资产独立趋势槽位 V1

- 数据截止：20260724。
- 四个风险资产各固定25%槽位；MA60>MA120时持有，否则转5年国债。
- 不做相对排名、不集中Top2、不叠加额外波动率风险层。
- 与更新后双动量对照统一使用 qfq、M0 T+1、5bps、ETF免印花税。
- 与 Quality 日收益相关性：0.533。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| cross_asset_independent_trend_slots_v1 | 2015_2017 | -2.63% | -47.46% | -0.016 | -0.056 | -22.76% | 4.82x |
| cross_asset_independent_trend_slots_v1 | 2018_2020 | 9.26% | -13.81% | 0.736 | 0.671 | -4.48% | 3.98x |
| cross_asset_independent_trend_slots_v1 | 2021_2023 | -0.80% | -11.72% | -0.055 | -0.068 | 29.15% | 4.89x |
| cross_asset_independent_trend_slots_v1 | 2024_latest | 14.10% | -12.82% | 0.935 | 1.099 | -7.68% | 3.59x |
| cross_asset_independent_trend_slots_v1 | full | 4.62% | -48.93% | 0.371 | 0.094 | 9.45% | 4.32x |
| cross_asset_dual_momentum_same_data_control | 2015_2017 | -1.23% | -55.56% | 0.131 | -0.022 | -18.84% | 5.30x |
| cross_asset_dual_momentum_same_data_control | 2018_2020 | 14.75% | -14.86% | 0.977 | 0.993 | 15.23% | 4.17x |
| cross_asset_dual_momentum_same_data_control | 2021_2023 | -2.17% | -24.67% | -0.078 | -0.088 | 25.31% | 3.22x |
| cross_asset_dual_momentum_same_data_control | 2024_latest | 21.40% | -19.04% | 1.037 | 1.123 | 15.06% | 3.10x |
| cross_asset_dual_momentum_same_data_control | full | 7.57% | -55.56% | 0.439 | 0.136 | 69.30% | 3.80x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 11.09% | -37.31% | 0.487 |
| 2016 | -10.38% | -16.45% | -0.600 |
| 2017 | -1.65% | -5.50% | -0.251 |
| 2018 | 0.28% | -7.62% | 0.081 |
| 2019 | 6.20% | -12.06% | 0.564 |
| 2020 | 21.23% | -13.81% | 1.113 |
| 2021 | 7.50% | -10.78% | 0.706 |
| 2022 | -8.08% | -9.52% | -1.051 |
| 2023 | -0.49% | -6.29% | -0.075 |
| 2024 | 2.56% | -7.53% | 0.333 |
| 2025 | 37.75% | -6.40% | 2.437 |
| 2026 | -1.93% | -12.82% | 0.043 |

## 平均资产暴露

| 资产 | 平均目标权重 |
|---|---:|
| 510300.SH | 14.31% |
| 510500.SH | 13.77% |
| 159915.SZ | 13.41% |
| 518880.SH | 16.85% |
| 511010.SH | 41.67% |

## 相对双动量

- 全样本回撤改善：6.62%。
- 2015–2017回撤改善：8.10%。
- 年化收益变化：-2.94%。
- Sharpe变化：-0.068。

## 固定门槛

- FAIL：full_annual_return_at_least_5pct
- FAIL：full_drawdown_within_25pct
- FAIL：full_sharpe_at_least_060
- FAIL：full_calmar_at_least_025
- PASS：full_positive_excess
- FAIL：at_least_three_positive_folds
- FAIL：worst_fold_drawdown_within_25pct
- FAIL：median_fold_sharpe_at_least_040
- FAIL：annual_turnover_below_4x
- PASS：quality_correlation_at_most_060
- FAIL：dual_full_drawdown_improves_15pct
- FAIL：dual_early_drawdown_improves_15pct
- FAIL：dual_return_loss_within_2pct

结论：终止并保留失败指纹，不注册生产。
