# 全球四资产周频20日动量数据可行性 V1

- 共同截止：20260728；共同日：2682。
- 完整周：539/539
  (100.00%)。
- 本阶段仅计算信号日前20日收益与Top2预览，不读取下一周收益。

| 代码 | 资产 | Top2入选占比 |
|---|---|---:|
| 159941.SZ | 纳斯达克100ETF | 29.7% |
| 513500.SH | 标普500ETF | 30.3% |
| 518880.SH | 黄金ETF | 22.7% |
| 511010.SH | 5年国债ETF | 17.3% |

## 冻结门禁

- PASS：all_four_assets_present
- PASS：common_days_at_least_2600
- PASS：complete_week_share_at_least_99pct
- PASS：target_share_at_least_99pct
- PASS：fresh_within_five_days
- PASS：selection_share_between_10_and_40pct
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

结论：`CONTINUE_TO_FIXED_BACKTEST`。
