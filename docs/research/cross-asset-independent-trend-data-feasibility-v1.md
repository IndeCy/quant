# 五资产独立趋势槽位数据可行性 V1

- 数据截止：20260724。
- 风险资产各固定25%槽位；MA60>MA120时启用，否则转5年国债。
- 本阶段不读取未来收益，不进行相对排名或参数搜索。
- 可构造月末：138 /
  138，重复/无效：0 /
  0。
- 共同交易日保留比例：95.81%。

| 资产 | 起始 | 截止 | 行数 |
|---|---|---|---:|
| 510300.SH | 20130104 | 20260728 | 3293 |
| 510500.SH | 20130315 | 20260724 | 3244 |
| 159915.SZ | 20130104 | 20260724 | 3290 |
| 518880.SH | 20130729 | 20260728 | 3160 |
| 511010.SH | 20130325 | 20260728 | 3242 |

| 风险资产 | 趋势开启比例 |
|---|---:|
| 510300.SH | 57.25% |
| 510500.SH | 55.07% |
| 159915.SZ | 53.62% |
| 518880.SH | 67.39% |

## 冻结门禁

- FAIL：all_assets_latest_same_date
- PASS：data_is_fresh
- PASS：common_calendar_retention
- PASS：monthly_states_constructible
- PASS：states_are_not_degenerate
- PASS：zero_duplicate_rows
- PASS：zero_invalid_rows

结论：`REJECTED_BEFORE_BACKTEST`。未通过时不执行收益回测。
