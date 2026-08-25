# A股科技×红利低波×黄金固定等权 V1

- 数据共同截止：20260728。
- 固定持有科技龙头ETF、红利低波ETF、黄金ETF，各三分之一。
- 月末恢复等权；不做行业排名、趋势择时、权重搜索或风险层。
- 信号下一交易日经M0执行，统一qfq、5bps，ETF免印花税。
- 对照：科技/红利50/50、科技单持、场内标普500、纳指/黄金60/40。
- 与Quality日收益相关性：0.646。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
| 2020_2021 | 14.39% | -14.28% | 1.025 | 1.008 | 0.82x |
| 2022_2023 | 0.17% | -12.48% | 0.071 | 0.013 | 0.37x |
| 2024_latest | 27.84% | -12.31% | 1.613 | 2.262 | 0.61x |
| locked_test | 27.84% | -12.31% | 1.613 | 2.262 | 0.61x |
| full | 14.77% | -14.28% | 1.046 | 1.035 | 0.60x |

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| china_tech_dividend_gold_equal_v1 | 14.77% | -14.28% | 1.046 | 1.035 |
| china_tech_dividend_50_50_control | 13.82% | -22.05% | 0.801 | 0.627 |
| china_tech_direct_control | 10.97% | -53.88% | 0.502 | 0.204 |
| sp500_direct_china_barbell_control | 14.88% | -29.26% | 0.812 | 0.509 |
| nasdaq_gold_60_40_china_barbell_control | 18.83% | -21.57% | 1.067 | 0.873 |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2020 | 24.26% | -14.28% | 1.374 |
| 2021 | 4.51% | -8.48% | 0.470 |
| 2022 | -9.04% | -12.48% | -0.711 |
| 2023 | 9.58% | -5.89% | 0.967 |
| 2024 | 24.14% | -8.89% | 1.519 |
| 2025 | 41.95% | -6.35% | 2.647 |
| 2026 | 11.76% | -12.31% | 0.640 |

## 尾部诊断

- 年化波动：14.14%
- 最差单日：-6.12%
- 95% Expected Shortfall：-2.03%
- 最长水下期：371个交易日

## 冻结门槛

- PASS：data_audit
- PASS：full_return_at_least_10pct
- PASS：full_drawdown_within_28pct
- PASS：full_sharpe_at_least_075
- PASS：full_calmar_at_least_040
- FAIL：return_lift_vs_sp500_at_least_05pct
- PASS：sharpe_lift_vs_tech_dividend_at_least_010
- PASS：drawdown_improvement_vs_tech_dividend_at_least_5pct
- PASS：drawdown_improvement_vs_tech_at_least_15pct
- PASS：all_three_folds_positive
- PASS：worst_fold_drawdown_within_30pct
- PASS：median_fold_sharpe_at_least_055
- PASS：locked_return_at_least_10pct
- PASS：locked_drawdown_within_22pct
- PASS：locked_sharpe_at_least_070
- PASS：at_least_five_positive_years
- PASS：annual_turnover_below_1x
- PASS：stress_return_at_least_9pct
- PASS：stress_sharpe_at_least_065
- PASS：worst_day_within_8pct
- PASS：expected_shortfall_95_within_35pct
- FAIL：quality_correlation_at_most_050

结论：未通过冻结门槛，归档且不注册。
