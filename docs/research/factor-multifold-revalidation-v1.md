# 独立因子多折复验 V1

- 数据截止：20260724。
- 候选在运行前固定为业绩预告确定性动量、重要股东净增持。
- 两个候选均原样复用因子、股票池、Top40、风险层和M0成交口径。
- 本研究使用过2022年后的结果做候选筛选，因此只能用于回顾性诊断。

| 候选 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
| earnings_forecast_momentum_v1 | 2015_2017 | 23.14% | -36.79% | 0.872 | 0.629 | 67.75% | 13.53x |
| earnings_forecast_momentum_v1 | 2018_2020 | -1.01% | -32.64% | 0.092 | -0.031 | -36.65% | 11.31x |
| earnings_forecast_momentum_v1 | 2021_2023 | -8.16% | -42.77% | -0.253 | -0.191 | 9.68% | 8.99x |
| earnings_forecast_momentum_v1 | 2024_latest | 28.94% | -19.41% | 1.079 | 1.491 | 40.77% | 11.99x |
| earnings_forecast_momentum_v1 | full | 9.54% | -51.47% | 0.479 | 0.185 | 120.05% | 11.45x |
| insider_net_buying_v1 | 2015_2017 | 23.37% | -37.24% | 0.886 | 0.628 | 68.74% | 11.15x |
| insider_net_buying_v1 | 2018_2020 | -11.48% | -48.02% | -0.353 | -0.239 | -63.49% | 7.64x |
| insider_net_buying_v1 | 2021_2023 | 8.06% | -29.79% | 0.490 | 0.271 | 56.51% | 7.59x |
| insider_net_buying_v1 | 2024_latest | 16.58% | -25.60% | 0.699 | 0.648 | -0.18% | 9.01x |
| insider_net_buying_v1 | full | 8.08% | -57.20% | 0.434 | 0.141 | 81.70% | 9.02x |

## 固定多折门槛

| 候选 | 结论 | 正收益折 | 最差折回撤 | 折Sharpe中位数 |
|---|---|---:|---:|---:|
| earnings_forecast_momentum_v1 | FAIL | 2/4 | -42.77% | 0.482 |
| insider_net_buying_v1 | FAIL | 3/4 | -48.02% | 0.595 |

未通过项：

- earnings_forecast_momentum_v1：full_drawdown_within_30pct、full_sharpe_at_least_055、at_least_three_positive_folds、worst_fold_drawdown_within_30pct、annual_turnover_below_10x
- insider_net_buying_v1：full_drawdown_within_30pct、full_sharpe_at_least_055、worst_fold_drawdown_within_30pct

## 候选相关性

| 阶段 | 两候选日收益相关性 |
|---|---:|
| 2015_2017 | 0.898 |
| 2018_2020 | 0.915 |
| 2021_2023 | 0.825 |
| 2024_latest | 0.874 |
| full | 0.882 |

## 既有稳健策略对照

Quality Balanced Value 的全样本年化为
12.96%，最大回撤
-25.46%，Sharpe
0.687。

## 结论

决策：`REJECT_ALL_CANDIDATES`。

即使存在通过者，也不能直接注册生产策略。候选筛选已经观察了全部历史数据，
下一份有效证据只能来自固定定义后的新前瞻Paper，不得继续在历史窗口上调参数。
