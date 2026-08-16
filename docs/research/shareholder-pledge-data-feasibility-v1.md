# 股东质押治理风险数据可行性 V1

本实验只验证数据口径，不读取收益，也不执行回测。

| 公告窗口 | 状态 | 行数 | 股票数 | 错误 |
|---|---|---:|---:|---|
| 20150101~20150131 | OK | 511 | 243 | - |
| 20190101~20190131 | OK | 1500 | 308 | - |
| 20230101~20230131 | OK | 1317 | 306 | - |
| 20260701~20260724 | OK | 1075 | 350 | - |

## 数据语义

- 总记录：4403，覆盖股票：979。
- 缺失必要字段：无。
- 事件身份完整率：98.89%。
- 完全重复记录：167。
- 同事件同公告日状态冲突：81。
- 已解押记录：3335。
- 公告行携带未来解押状态：115。

## 可信门禁

- PASS：all_windows_accessible
- PASS：cross_period_coverage
- PASS：required_columns_present
- FAIL：no_window_hits_row_limit
- PASS：announcement_dates_complete
- FAIL：event_identity_reconstructible
- FAIL：release_state_point_in_time_safe

## 结论

- 决策：`REJECTED_BEFORE_BACKTEST`。
- 原始业务记录未落盘。
- 若存在“未来解押状态”，仅按 `ann_date <= signal_date` 过滤仍会泄露后来信息；
  在缺少解押公告可见日期时，不得进入因子回测。
