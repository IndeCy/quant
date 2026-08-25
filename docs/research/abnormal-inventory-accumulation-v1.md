# 异常存货积累因子 V1

- 数据截止：20260724。
- 因子：`ln(存货同比倍数)-ln(营收同比倍数)`，越低越好。
- 财务口径：一般工商业、连续两年1231年报、逐报表 `f_ann_date` as-of。
- 股票池：上市满3年，剔除ST/退市/停牌/成交额最低20%。
- 组合与执行：Top40月频等权，qfq、M0 T+1、5bps及固定风险层。
- 可投股票数最少：1457。
- 有效候选最少/中位/最新：1378 /
  2324 / 3878。
- 有效覆盖率最少/中位：91.4% /
  93.9%。

## 数据门禁

- PASS：full_qualified_month_share
- PASS：locked_qualified_month_share
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows

## 因子归因

- 与纯存货增长/营收增长/120日动量 Spearman 中位数：
  0.650 /
  -0.384 /
  -0.007。
- 与纯低存货增长/高动量 Top40 重合中位数：
  60.0% /
  2.5%。
- 最高分并列数中位/最大：
  24 /
  39；
  Top40 落在缩尾并列区的中位占比：
  60.0%。
- 入选异常积累/存货增长/营收增长中位数：
  -1.625 /
  -1.162 /
  0.380。
- 与 Quality Balanced Value 日收益相关性：
  0.752。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
| train | -1.98% | -65.85% | 0.061 | -0.030 | 5.05% | 10.64x |
| validation | 11.19% | -30.03% | 0.546 | 0.373 | -38.06% | 6.11x |
| locked_test | -2.57% | -46.03% | 0.022 | -0.056 | -14.95% | 7.03x |
| full | 1.18% | -71.73% | 0.175 | 0.016 | -41.94% | 8.48x |

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
| 2015 | 165.46% | -33.81% | 2.929 |
| 2016 | -10.10% | -18.32% | -0.264 |
| 2017 | -20.62% | -21.73% | -1.536 |
| 2018 | -46.86% | -47.73% | -2.564 |
| 2019 | 15.41% | -25.56% | 0.677 |
| 2020 | 4.40% | -20.64% | 0.295 |
| 2021 | 9.73% | -16.64% | 0.548 |
| 2022 | -1.52% | -23.42% | 0.076 |
| 2023 | -10.24% | -19.54% | -0.630 |
| 2024 | -5.54% | -35.17% | -0.015 |
| 2025 | 26.83% | -13.57% | 1.198 |
| 2026 | -29.27% | -27.65% | -1.188 |

## 固定晋级门槛

- FAIL：locked_test_annual_return_at_least_8pct
- FAIL：locked_test_sharpe_at_least_055
- FAIL：locked_test_drawdown_within_30pct
- FAIL：locked_test_positive_excess
- FAIL：full_annual_return_at_least_10pct
- FAIL：full_sharpe_at_least_065
- FAIL：full_drawdown_within_32pct
- FAIL：annual_turnover_below_8x
- FAIL：at_least_nine_positive_years
- FAIL：quality_correlation_at_most_075

结论：未通过固定门槛，终止且不注册生产策略。
