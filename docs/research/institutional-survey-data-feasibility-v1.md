# 机构调研关注度数据可行性 V1

| 调研窗口 | 状态 | 行数 | 股票数 | 错误 |
|---|---|---:|---:|---|
| 20150101~20150107 | EMPTY | 0 | 0 | - |
| 20190101~20190107 | EMPTY | 0 | 0 | - |
| 20230101~20230107 | OK | 400 | 22 | - |
| 20260701~20260707 | OK | 400 | 42 | - |

- 总记录：800，覆盖股票：63。
- 缺失必要业务字段：无。
- 公开可见时间字段：
  无。

## 可信门禁

- PASS：all_windows_accessible
- FAIL：cross_period_coverage
- PASS：required_columns_present
- FAIL：no_window_hits_row_limit
- FAIL：public_visibility_timestamp_present
- PASS：survey_dates_complete

## 结论

- 决策：`REJECTED_BEFORE_CACHE_OR_BACKTEST`。
- `surv_date` 只表示调研发生日，不等于记录公开日。
- 不允许用固定延迟伪造公告日期；原始记录未缓存，也未执行回测。
