# 公司回购因子数据可行性 V1

- 审计年度：2024，数据截止：20260724。
- 接口总记录：13410，覆盖股票：2273。
- 有金额和截止日的完成记录：9417，覆盖
  2085 只股票。
- 同股票同公告日多记录分组：
  155。
- 年内至少四次“完成”累计披露的股票：
  1204。

## 可信因子门禁

- PASS：announcement_date_visibility
- PASS：long_history_coverage
- FAIL：stable_plan_identity
- FAIL：incremental_executed_amount
- FAIL：open_market_purchase_separable

## 结论

接口中的“完成”包含连续累计实施进度；同一股票同一公告日也可能存在多个方案。
现有字段没有稳定方案 ID、回购目的或本期新增执行金额。直接求和会重复累计，
按最大值又会错误合并多个方案，因此本候选在数据语义阶段终止，未进入回测。
