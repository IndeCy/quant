# Fundamental Announcement Drift V1 Study

- 数据截止：20260723
- 固定主策略：季度公告后90日内，利润与营收同比、ROA及经营现金流均为正。
- 三因子等权：利润同比、营收同比、OCF_TO_OR；Top40月频等权。
- 所有财务数据通过f_ann_date as-of门面，策略不读取原始财务表。
- 与Quality Balanced Value日收益相关性：0.722。
- 与无现金验证增长对照相关性：0.944。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| quarterly_growth_drift_without_cash_v1 | validation | 25.01% | -26.30% | 1.042 | 0.951 | 16.87% | 1335.74% |
| quarterly_growth_drift_without_cash_v1 | locked_test | 2.70% | -47.12% | 0.234 | 0.057 | 6.27% | 1351.32% |
| quarterly_growth_drift_without_cash_v1 | full | 8.73% | -52.84% | 0.446 | 0.165 | 95.30% | 1444.81% |
| fundamental_announcement_drift_v1 | validation | 26.91% | -19.67% | 1.122 | 1.368 | 25.40% | 1274.42% |
| fundamental_announcement_drift_v1 | locked_test | 10.30% | -31.88% | 0.506 | 0.323 | 47.44% | 1319.01% |
| fundamental_announcement_drift_v1 | full | 9.44% | -58.99% | 0.473 | 0.160 | 114.25% | 1424.94% |

## 主策略年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 84.28% | -40.54% | 1.823 |
| 2016 | -5.28% | -16.08% | -0.065 |
| 2017 | -2.37% | -17.60% | -0.044 |
| 2018 | -43.57% | -45.43% | -1.916 |
| 2019 | 44.26% | -14.46% | 1.700 |
| 2020 | 19.14% | -19.67% | 0.770 |
| 2021 | 13.33% | -17.70% | 0.744 |
| 2022 | -24.91% | -31.88% | -0.925 |
| 2023 | -2.17% | -18.23% | -0.047 |
| 2024 | 28.51% | -19.67% | 0.950 |
| 2025 | 57.93% | -17.21% | 2.078 |
| 2026 | 2.90% | -20.77% | 0.247 |

## 固定晋级门槛

- PASS：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- FAIL：locked_test_drawdown_within_30pct
- PASS：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- FAIL：annual_turnover_below_8x
- FAIL：at_least_nine_positive_years
- PASS：quality_correlation_at_most_075

结论：终止，不注册生产策略。
