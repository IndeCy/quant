# A股ETF周频短期反转数据可行性 V1

- 数据共同截止：20260617。
- 共同交易日：2047。
- 完整周截面：381/381
  (100.00%)。
- 本阶段只计算信号日向后看5日收益，不读取持有期收益、不执行回测。

| 代码 | 名称 | 2019后日成交额中位数（源字段单位） |
|---|---|---:|
| 510050.SH | 上证50ETF | 1,855,456 |
| 510300.SH | 沪深300ETF | 2,344,410 |
| 510500.SH | 中证500ETF | 1,348,628 |
| 512100.SH | 中证1000ETF | 629,092 |
| 159915.SZ | 创业板ETF | 1,150,263 |
| 510880.SH | 红利ETF | 241,963 |
| 512880.SH | 证券ETF | 1,219,644 |
| 512800.SH | 银行ETF | 266,865 |
| 512660.SH | 军工ETF | 375,798 |
| 159928.SZ | 消费ETF | 144,437 |
| 512010.SH | 医药ETF | 366,964 |
| 512400.SH | 有色ETF | 138,188 |

## 冻结门禁

- PASS：all_twelve_assets_present
- PASS：all_assets_listed_before_study
- PASS：common_days_at_least_1800
- PASS：weekly_constructible_share_at_least_98pct
- PASS：all_median_amount_at_least_30000
- FAIL：data_fresh_within_five_days
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

结论：`REJECTED_BEFORE_BACKTEST`。
