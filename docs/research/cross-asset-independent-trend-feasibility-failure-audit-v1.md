# 五资产独立趋势数据门禁失败归因 V1

- 来源决策：`REJECTED_BEFORE_BACKTEST`。
- 分类：`LOCAL_INCREMENT_GAP_UPSTREAM_AVAILABLE`。
- 本地缺失、上游可用行：4。

## 缺失日期

- `510500.SH`：20260727, 20260728
- `159915.SZ`：20260727, 20260728

## 冻结检查

- PASS：source_only_latest_date_check_failed
- PASS：upstream_all_symbols_reach_as_of
- PASS：at_least_one_local_row_missing_upstream_available
- PASS：every_missing_row_exists_upstream
- PASS：common_sample_remains_fresh

本审计仅只读比较日期，不补写本地数据库、不绕过可行性门禁，也未运行策略回测。
