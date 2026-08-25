# 连续现金分红增长 V3

- 数据截止：20260724。
- V2 保留分红时效修复；V3 只把头部缩尾同分改为无参数百分位排名。
- 因子原值、Top40、月频、M0、风险层和样本分段均未改变。
- 与 Quality Balanced Value 日收益相关性：0.641。
- 月度有效候选数：最少 168，中位数
  758，最新 733。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| train | -4.59% | -40.48% | -0.112 | -0.113 | -36.57% | 4.64x |
| validation | 5.44% | -29.88% | 0.348 | 0.182 | 18.87% | 4.49x |
| locked_test | 0.64% | -36.76% | 0.138 | 0.017 | -27.39% | 5.15x |
| full | 0.91% | -42.31% | 0.151 | 0.022 | -52.42% | 4.78x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2017 | 4.76% | -11.28% | 0.366 |
| 2018 | -34.81% | -34.74% | -1.729 |
| 2019 | 30.09% | -17.64% | 1.290 |
| 2020 | 20.79% | -14.81% | 0.875 |
| 2021 | 15.88% | -9.35% | 0.944 |
| 2022 | -18.92% | -29.88% | -0.741 |
| 2023 | -13.48% | -23.35% | -0.969 |
| 2024 | 3.26% | -21.85% | 0.253 |
| 2025 | 30.36% | -16.49% | 1.405 |
| 2026 | -19.48% | -21.28% | -0.856 |

## 固定晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- FAIL：locked_test_drawdown_within_30pct
- FAIL：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- PASS：annual_turnover_below_8x
- FAIL：at_least_seven_positive_years
- PASS：quality_correlation_at_most_075

结论：终止分红增长方向，不注册生产策略。
