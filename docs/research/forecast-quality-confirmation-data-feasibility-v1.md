# 业绩预告 × Quality 确认可行性 V1

- 数据截止：20260724，月末截面：138。
- 输入：90日内正向业绩预告强度与公告日可见的 Quality 三因子。
- 组合：两项横截面百分位秩各 50%，本阶段不读取未来收益。
- 交集候选最少/中位/最新：80 /
  370 / 80。
- 全样本/2022年后可构造 Top40 比例：
  100.00% /
  100.00%。
- 因子唯一值中位数：299。
- Top40 日均成交额中位数：
  217.9 百万元。
- 预告分与 Quality 分月度 Spearman 中位数：
  -0.344。
- 公告越界/重复/无效评分：
  0 / 0 /
  0。

## 冻结门禁

- PASS：full_top40_constructible_share
- PASS：locked_top40_constructible_share
- PASS：top40_liquidity
- PASS：inputs_not_redundant
- PASS：zero_visibility_violations
- PASS：zero_duplicate_rows
- PASS：zero_invalid_scores

## 结论

- 决策：`CONTINUE_TO_FIXED_BACKTEST`。
- 未通过时不执行收益回测，也不注册策略。
