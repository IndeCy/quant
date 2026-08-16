# 国内红利低波黄金国债三资产数据可行性 V1

- 共同截止：20260728；共同日：1822。
- 2020后月末信号：78。
- 本阶段不计算组合收益，只审查可投资性和同期资产分散性。

| 代码 | 资产 | 日成交额中位数（源字段单位） |
|---|---|---:|
| 512890.SH | 红利低波ETF | 31,215 |
| 518880.SH | 黄金ETF | 1,287,630 |
| 511010.SH | 5年国债ETF | 259,579 |

| 资产A | 资产B | 日收益相关性 |
|---|---|---:|
| 512890.SH | 518880.SH | 0.059 |
| 511010.SH | 512890.SH | -0.227 |
| 511010.SH | 518880.SH | 0.099 |

## 冻结门槛

- PASS：all_three_assets_present
- PASS：all_assets_start_before_2020
- PASS：common_days_at_least_1800
- PASS：monthly_signals_at_least_75
- PASS：fresh_within_five_days
- FAIL：all_median_amount_at_least_50000
- PASS：pairwise_correlation_at_most_060
- PASS：no_duplicate_dates
- PASS：all_prices_positive

结论：`REJECTED_BEFORE_BACKTEST`。
