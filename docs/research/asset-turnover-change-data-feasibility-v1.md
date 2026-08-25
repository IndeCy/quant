# 资产周转率改善数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 总候选最少/中位/最新：1396 /
  2365 / 3927。
- 唯一因子值最少/中位/最新：1396 /
  2365 / 3927。
- 最新变化值 P1/中位/P99：-0.3724 /
  -0.0016 / 0.3427。
- 最新周转率水平 P1/中位/P99：0.0647 /
  0.4779 / 2.4219。
- 与周转率水平的月度 Spearman 中位数：
  0.107。
- 公告日越界/重复主键：0 /
  0。

## 冻结门槛

- PASS：candidate_month_share
- PASS：unique_value_month_share
- PASS：locked_candidate_month_share
- PASS：locked_unique_value_month_share
- PASS：zero_visibility_violations
- PASS：zero_duplicate_signal_symbol_rows
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
