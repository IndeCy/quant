# Fundamental Announcement Drift Buffered V2 Study

- 数据截止：20260723
- Alpha与V1完全一致，只把组合规则改为Top40进入、Top80退出。
- 过期公告或不再满足基本面门禁的股票立即退出，不受缓冲保护。
- 统一口径：季度f_ann_date as-of、Top40等权、月频、qfq、M0 T+1及原风险层。
- 与V1日收益相关性：0.977。
- 与Quality Balanced Value日收益相关性：0.726。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| fundamental_announcement_drift_unbuffered_v1 | validation | 26.91% | -19.67% | 1.122 | 1.368 | 25.40% | 1274.42% |
| fundamental_announcement_drift_unbuffered_v1 | locked_test | 10.30% | -31.88% | 0.506 | 0.323 | 47.44% | 1319.01% |
| fundamental_announcement_drift_unbuffered_v1 | full | 9.44% | -58.99% | 0.473 | 0.160 | 114.25% | 1424.94% |
| fundamental_announcement_drift_buffered_v2 | validation | 24.23% | -24.07% | 1.028 | 1.007 | 13.45% | 1222.44% |
| fundamental_announcement_drift_buffered_v2 | locked_test | 9.15% | -35.15% | 0.467 | 0.260 | 40.59% | 1230.05% |
| fundamental_announcement_drift_buffered_v2 | full | 9.23% | -55.85% | 0.465 | 0.165 | 108.60% | 1304.04% |

## V2年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 103.69% | -42.38% | 2.026 |
| 2016 | -1.11% | -15.12% | 0.095 |
| 2017 | -3.37% | -17.83% | -0.103 |
| 2018 | -45.71% | -47.06% | -2.058 |
| 2019 | 44.93% | -13.51% | 1.725 |
| 2020 | 9.00% | -24.07% | 0.451 |
| 2021 | 16.37% | -19.25% | 0.856 |
| 2022 | -28.67% | -32.18% | -1.110 |
| 2023 | -3.53% | -20.02% | -0.131 |
| 2024 | 26.77% | -19.73% | 0.907 |
| 2025 | 60.55% | -16.89% | 2.138 |
| 2026 | 3.49% | -18.70% | 0.265 |

## 固定晋级门槛

- PASS：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- FAIL：locked_test_drawdown_within_30pct
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- FAIL：annual_turnover_below_8x
- FAIL：turnover_reduced_by_at_least_30pct
- PASS：full_return_within_1pct_of_v1
- FAIL：locked_return_within_1pct_of_v1
- FAIL：at_least_nine_positive_years
- PASS：quality_correlation_at_most_075

结论：终止，不注册生产策略。
