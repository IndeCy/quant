# 当前观察策略 Alpha 来源地图 V1

- 数据截止：20260724。
- 严格共同历史：20200615 至 20260724，
  1482 个交易日。
- 仅纳入拥有至少1000个共同净值观测的正式观察策略。
- 收益来自统一 monitoring 净成本事实表；510300基准取Quality统一曲线。
- 本研究不生成新组合、不选择权重、不修改任何策略。

## 策略表现

| 策略 | 年化收益 | 最大回撤 | 年化波动 | Sharpe | Beta | 年化回归Alpha | 上行捕获 | 下行捕获 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Quality Alpha | 16.58% | -31.88% | 20.88% | 0.839 | 0.822 | 12.84% | 85.3% | 74.2% |
| Balanced Value | 14.07% | -24.84% | 19.77% | 0.765 | 0.692 | 11.13% | 66.0% | 55.1% |
| Defensive Assets | 12.98% | -16.83% | 14.45% | 0.917 | 0.502 | 10.43% | 49.6% | 39.6% |
| Mainline Chain | 15.61% | -43.77% | 38.27% | 0.570 | 0.774 | 18.14% | 87.0% | 76.0% |

## 普通日收益相关

| 策略 | Quality Alpha | Balanced Value | Defensive Assets | Mainline Chain |
|---|---:|---:|---:|---:|
| Quality Alpha | 1.000 | 0.791 | 0.786 | 0.299 |
| Balanced Value | 0.791 | 1.000 | 0.984 | 0.178 |
| Defensive Assets | 0.786 | 0.984 | 1.000 | 0.178 |
| Mainline Chain | 0.299 | 0.178 | 0.178 | 1.000 |

## 510300下跌日相关

| 策略 | Quality Alpha | Balanced Value | Defensive Assets | Mainline Chain |
|---|---:|---:|---:|---:|
| Quality Alpha | 1.000 | 0.752 | 0.747 | 0.230 |
| Balanced Value | 0.752 | 1.000 | 0.980 | 0.138 |
| Defensive Assets | 0.747 | 0.980 | 1.000 | 0.134 |
| Mainline Chain | 0.230 | 0.138 | 0.134 | 1.000 |

## 剔除510300 Beta后的残差相关

| 策略 | Quality Alpha | Balanced Value | Defensive Assets | Mainline Chain |
|---|---:|---:|---:|---:|
| Quality Alpha | 1.000 | 0.604 | 0.597 | 0.032 |
| Balanced Value | 0.604 | 1.000 | 0.972 | -0.101 |
| Defensive Assets | 0.597 | 0.972 | 1.000 | -0.098 |
| Mainline Chain | 0.032 | -0.101 | -0.098 | 1.000 |

## 两两风险分散

| 左策略 | 右策略 | 普通相关 | 50/50波动分散率 | 市场下跌日共同亏损比例 |
|---|---|---:|---:|---:|
| Quality Alpha | Balanced Value | 0.791 | 1.057 | 56.1% |
| Quality Alpha | Defensive Assets | 0.786 | 1.056 | 56.0% |
| Quality Alpha | Mainline Chain | 0.299 | 1.213 | 40.2% |
| Balanced Value | Defensive Assets | 0.984 | 1.004 | 61.1% |
| Balanced Value | Mainline Chain | 0.178 | 1.259 | 36.1% |
| Defensive Assets | Mainline Chain | 0.178 | 1.219 | 35.0% |

## 独立收益源

- 普通相关矩阵有效押注数：1.83 / 4。
- 下跌日相关矩阵有效押注数：1.92 / 4。
- Beta残差相关矩阵有效押注数：2.17 / 4。
- 相关阈值0.75形成的收益源簇：[['Balanced Value', 'Defensive Assets'], ['Mainline Chain'], ['Quality Alpha']]。

## 研究结论

- 判定：`ALPHA_SOURCE_CONCENTRATION_CONFIRMED`。
- 剔除市场Beta后有效押注数仍不足2.5，策略数量高估了真正的收益源数量。
- 下一类候选必须优先证明与现有收益源的残差相关低于0.75，
  再进入未来收益回测；仅改变Quality内部排序不再视为新增Alpha来源。
