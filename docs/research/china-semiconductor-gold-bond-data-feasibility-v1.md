# 半导体黄金国债三资产数据可行性 V1

- 共同截止：20260728；共同日：1677。
- 2020后月末信号：78。
- 仅检查数据、流动性和同期相关性，不计算组合收益。

| 代码 | 资产 | 日成交额中位数（源字段单位） |
|---|---|---:|
| 512480.SH | 半导体ETF | 795,250 |
| 518880.SH | 黄金ETF | 1,287,234 |
| 511010.SH | 5年国债ETF | 259,579 |

| 资产A | 资产B | 日收益相关性 |
|---|---|---:|
| 512480.SH | 518880.SH | 0.070 |
| 511010.SH | 512480.SH | -0.176 |
| 511010.SH | 518880.SH | 0.090 |

## 冻结门槛

- PASS：all_three_assets_present
- PASS：common_days_at_least_1600
- PASS：monthly_signals_at_least_75
- PASS：fresh_within_five_days
- PASS：all_median_amount_at_least_100000
- PASS：pairwise_correlation_at_most_060
- PASS：no_duplicate_dates
- PASS：all_prices_positive

结论：`CONTINUE_TO_FIXED_BACKTEST`。
