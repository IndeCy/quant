# A股科技ETF周频5日反转数据可行性 V1

- 共同截止：20260728；共同交易日：1667。
- 完整周截面：336/336
  (100.00%)。
- 仅生成信号日向后看5日收益排名，不读取下一周收益。

| 代码 | 名称 | 2020后日成交额中位数（源字段单位） |
|---|---|---:|
| 512480.SH | 半导体ETF | 795,250 |
| 515880.SH | 通信ETF | 135,636 |
| 512720.SH | 计算机ETF | 53,251 |
| 512930.SH | 人工智能ETF | 11,572 |
| 515000.SH | 科技龙头ETF | 86,074 |

## 冻结门禁

- PASS：all_assets_present
- PASS：common_days_at_least_1600
- PASS：complete_week_share_at_least_99pct
- FAIL：all_median_amount_at_least_30000
- PASS：fresh_within_five_days
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

结论：`REJECTED_BEFORE_BACKTEST`。
