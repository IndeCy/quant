# 净派息收益率组合依赖可行性 V1

| 依赖实验 | 状态 | 结论 | 原因 |
|---|---|---|---|
| dividend_growth_persistence_v3 | SUCCESS | REJECTED | 分红增长百分位版未通过门槛，终止该方向并保留全部失败指纹 |
| net_share_issuance_investable_adjustment_feasibility_v2 | SUCCESS | REJECTED | 净股本发行V2仍未通过，终止于回测前且不再修订 |

## 结论

- 决策：`REJECTED_BEFORE_DATA_SCAN`。
- 组合依赖未全部通过时，不扫描数据、不回测，也不通过改名绕过失败指纹。
