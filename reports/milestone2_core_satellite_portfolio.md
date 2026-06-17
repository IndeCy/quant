# Milestone 2.1 Satellite Alpha Allocation Report

## 组合结构

- Core 70%：低波动资产，长期持有，低换手。
- Satellite 30%：动量/趋势增强，使用 signal → weight 连续映射，仅做增强。
- 权重由 `CoreSatelliteFactorPortfolio` 决定，策略信号不直接决定权重。
- Satellite 权重机制：softmax rank mapping + confidence weighting + volatility scaling + turnover penalty。

## 收益、换手与回撤对比

| 组合 | 总收益率 | 年化收益率 | 最大回撤 | 年化波动率 | 夏普比率 | 平均月换手 | 稳定性评分 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Core低波 | 7.99% | 7.99% | 0.00% | 0.17% | 45.21 | 4.94% | 0.08 |
| Satellite旧等权 | -15.11% | -15.11% | -24.69% | 9.95% | -1.60 | 95.83% | -0.61 |
| Satellite Alpha | 2.94% | 2.94% | -15.99% | 6.79% | 0.46 | 15.75% | 0.18 |
| Core-Satellite Alpha | 6.45% | 6.45% | -4.89% | 2.04% | 3.08 | 9.05% | 1.32 |

## 稳定性分析

旧 Satellite 使用单标的轮换，容易把高波动噪声直接放大成仓位。
Satellite Alpha 把同一批信号转成连续权重，并对高波动和信号突变降权。
Core-Satellite Alpha 用 Core 低波资产压住组合波动和回撤，用 Satellite 保留受约束的增强弹性。

## Satellite Alpha 判定

- Satellite 是否由负收益转为正收益：是。
- 组合级平均月换手是否受 35% 约束：是。

## 是否进入 Milestone 3

结论：是。若后续接真实股票池，仍需继续观察模拟盘成交失败、容量和持仓漂移。
