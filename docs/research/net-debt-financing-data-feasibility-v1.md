# 净债务融资数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 总候选最少/中位/最新：1557 /
  2512 / 3945。
- 净偿债候选最少/中位/最新：526 /
  994 / 1492。
- 全样本/2022年后可组成Top40月份：
  100.00% /
  100.00%。
- 最新 P1/中位/P99：-13.49% /
  0.01% / 18.83%；
  零值占比 11.94%。
- 借款/发债/偿债字段缺失率：
  13.68% /
  93.97% /
  12.11%。
- 三项全缺失：9.73%；
  公告越界/重复：0 /
  0。

## 冻结门槛

- PASS：candidate_month_share
- PASS：negative_candidate_month_share
- PASS：locked_negative_candidate_month_share
- PASS：all_components_missing_within_limit
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
