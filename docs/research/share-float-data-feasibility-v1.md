# 限售股解禁供给压力数据可行性 V1

本实验只检查数据，不读取收益或执行回测。

| 解禁窗口 | 状态 | 行数 | 股票数 | 错误 |
|---|---|---:|---:|---|
| 20150101~20150131 | OK | 1599 | 118 | - |
| 20190101~20190131 | OK | 6000 | 26 | - |
| 20230101~20230131 | OK | 6000 | 5 | - |
| 20260701~20260724 | OK | 6000 | 72 | - |

## 数据语义

- 总记录：19599，覆盖股票：216。
- 缺失必要字段：无。
- 有效正数解禁比例占比：
  70.97%。
- 公告不晚于解禁日占比：99.99%。
- 公告领先天数中位数：8 天。
- 完全重复记录：0。
- 同事件同公告日比例冲突：
  0。

## 可信门禁

- PASS：all_windows_accessible
- PASS：cross_period_coverage
- PASS：required_columns_present
- FAIL：no_window_hits_row_limit
- FAIL：valid_float_ratio
- PASS：known_before_event
- PASS：event_identity_reconstructible

## 结论

- 决策：`REJECTED_BEFORE_BACKTEST`。
- 原始业务记录未落盘。
- 只有全部门禁通过后，才允许另行冻结“未来60天解禁比例越低越好”的因子；
  当前结果不包含任何收益判断。
