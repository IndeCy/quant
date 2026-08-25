# Quality 盈利底线过滤可行性 V1

- 数据截止：20260724，月末截面：138。
- 基线：Quality 80% + E/P 10% + B/P 10%，Top20 月频等权。
- 唯一新增约束：最近五个连续年报的最低 ROA 必须大于 0。
- 本阶段不读取未来收益，不调整 Quality 权重。
- 基线候选中五年历史覆盖中位/最新：
  98.95% /
  99.94%。
- 过滤后候选最少/中位/最新：
  33 /
  1462 /
  1899。
- 全样本/2022年后可构造 Top20：
  100.00% /
  100.00%。
- 基线 Top20 被替换比例中位/最新：
  10.00% /
  0.00%。
- 公告越界/重复：
  0 / 0。

## 冻结门禁

- PASS：full_top20_constructible_share
- PASS：locked_top20_constructible_share
- PASS：floor_history_coverage
- PASS：filter_is_not_trivial
- PASS：filter_is_not_destructive
- PASS：zero_visibility_violations
- PASS：zero_duplicate_rows

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 未通过时不执行收益回测，也不创建策略配置。
