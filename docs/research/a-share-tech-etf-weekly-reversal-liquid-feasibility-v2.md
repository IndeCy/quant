# A股科技ETF周频5日反转流动性修订 V2

- V1未读取持有期收益，且唯一失败为人工智能ETF成交额中位数不足。
- V2仅剔除512930.SH；其余四只、5日窗口、周频和冻结门槛不变。
- 共同截止：20260728；完整周：
  336/336。

| 代码 | 名称 | 日成交额中位数（源字段单位） |
|---|---|---:|
| 512480.SH | 半导体ETF | 795,250 |
| 515880.SH | 通信ETF | 135,636 |
| 512720.SH | 计算机ETF | 53,251 |
| 515000.SH | 科技龙头ETF | 86,074 |

## 冻结门禁

- PASS：all_assets_present
- PASS：common_days_at_least_1600
- PASS：complete_week_share_at_least_99pct
- PASS：all_median_amount_at_least_30000
- PASS：fresh_within_five_days
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

结论：`CONTINUE_TO_FIXED_BACKTEST`。
