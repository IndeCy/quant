# 五年盈利稳定性数据可行性 V1

- 数据截止：20260724，月末截面 138 个。
- 候选最少/中位/最新：1353 /
  2184 / 3196。
- 唯一因子值最少：1353；
  零标准差占比最大值：0.00%。
- 最新 ROA 标准差 P1/中位/P99：0.261 /
  2.872 / 21.014。
- 最新五年平均/当前 ROA 中位数：
  5.34 /
  3.90。
- 稳定性得分与五年平均 ROA 的月度 Spearman 中位数：
  -0.246。
- 重复主键/未来可见/窗口长度异常：
  0 /
  0 /
  0。

## 冻结门槛

- PASS：full_qualified_month_share
- PASS：locked_qualified_month_share
- PASS：zero_duplicate_signal_symbol_rows
- PASS：zero_visibility_violations
- PASS：zero_observation_count_violations
- PASS：finite_latest_distribution

## 结论

CONTINUE_TO_FIXED_BACKTEST。本阶段未运行收益回测，也未注册生产策略。
