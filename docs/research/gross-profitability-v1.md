# Gross Profitability V1

- 数据截止：20260724；只使用已披露的1231年报。
- 因子：毛利率×总资产周转率，近似毛利润/平均总资产，越高越好。
- 原始报表复算相关性0.9862，误差中位数0.0006个百分点。
- 股票池不要求ROA或OCF，不使用Quality分位过滤。
- 执行：Top40月频等权，qfq、M0 T+1、5bps及固定风险层。
- 与 Quality Balanced Value 日收益相关性：0.719。
- 与ROA截面Spearman中位数：
  0.645；Top40重叠
  32.5%。
- 与动量Top40重叠中位数：
  0.0%。
- 历史持仓Gross Profitability中位数：
  58.80%。
- 月度候选数：最少 1416，中位数
  2416，最新 3930。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| train | 6.75% | -34.80% | 0.381 | 0.194 | 41.24% | 6.34x |
| validation | 21.79% | -21.88% | 1.006 | 0.996 | 2.95% | 3.14x |
| locked_test | -4.32% | -40.89% | -0.072 | -0.106 | -21.75% | 3.87x |
| full | 5.70% | -47.06% | 0.351 | 0.121 | 29.56% | 4.39x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 64.80% | -34.80% | 1.623 |
| 2016 | 6.25% | -13.45% | 0.374 |
| 2017 | 12.62% | -8.29% | 0.953 |
| 2018 | -29.00% | -32.73% | -1.146 |
| 2019 | 43.31% | -21.37% | 1.682 |
| 2020 | 28.92% | -13.77% | 1.206 |
| 2021 | -5.46% | -20.07% | -0.194 |
| 2022 | -8.94% | -29.28% | -0.247 |
| 2023 | -2.12% | -19.30% | -0.056 |
| 2024 | -4.15% | -32.17% | 0.016 |
| 2025 | 14.36% | -14.21% | 0.784 |
| 2026 | -28.88% | -24.42% | -1.481 |

## 固定晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- FAIL：locked_test_drawdown_within_30pct
- FAIL：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- PASS：annual_turnover_below_8x
- FAIL：at_least_nine_positive_years
- PASS：quality_correlation_at_most_075

结论：终止，不注册生产策略。
