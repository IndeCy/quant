# Dividend Quality V1 研究报告

## 数据审计

- 标准分红表：无
- 可用分红代理字段：comshare_payable_dvd, div_payt
- as-of 口径：仅使用 `f_ann_date <= signal_date` 的 1231 年报数据。
- 重要限制：当前 V1 使用 `COALESCE(comshare_payable_dvd, div_payt) / 市值代理`，不是标准 trailing cash dividend yield。

| 数据源 | 表 | 行数 | 分红相关字段 |
| --- | --- | --- | --- |
| daily | adj_factor | 18692731 | - |
| daily | daily | 17875849 | - |
| daily | daily_adj_cache | 17875849 | - |
| daily | stock_basic | 5936 | - |
| daily | stock_namechange | 3838 | - |
| daily | stock_name_manual | 8 | - |
| daily | stock_st | 325752 | - |
| daily | daily_adj | 17875849 | - |
| income | default_table | 312334 | compens_payout, div_payt, compens_payout_refu, prfshare_payable_dvd, comshare_payable_dvd, capit_comstock_div |
| balancesheet | default_table | 302500 | div_receiv, div_payable, policy_div_payable |
| cashflow | default_table | 299488 | incl_dvd_profit_paid_sc_ms |
| fina_indicator | default_table | 334921 | - |

## 分红覆盖度

| signal_date | 候选样本 | 有分红代理样本 | 清洗后样本 |
| --- | --- | --- | --- |
| 20250630 | 4324 | 1 | 1 |
| 20250731 | 4327 | 2 | 1 |
| 20250829 | 4331 | 1 | 1 |
| 20250930 | 4338 | 1 | 1 |
| 20251031 | 4345 | 1 | 1 |
| 20251128 | 4346 | 1 | 1 |
| 20251231 | 4366 | 1 | 1 |
| 20260130 | 4369 | 1 | 1 |
| 20260227 | 4376 | 1 | 1 |
| 20260331 | 4385 | 1 | 1 |
| 20260430 | 4368 | 0 | 0 |
| 20260529 | 4403 | 0 | 0 |

## 策略定义

- 股票池：上市满3年，剔除 ST/*ST/退市，剔除成交额最低20%，必须有分红代理记录。
- 因子：40% 股息率代理，30% ROE/ROA 质量，30% OCF_TO_OR 现金流质量。
- 约束：支付率 0~120%，资产负债率不高于85%，股息率和支付率按月横截面缩尾。
- 调仓：月频 Top20 等权。
- 成交：复用 M0 `ExecutionModel`，T日信号、T+1交易日成交。
- 基准：510300 ETF 复权口径。

## 回测结果

| 策略 | 年化收益 | 最大回撤 | 夏普比率 | 年化换手率 | 交易次数 | 失败委托数 | 执行成本影响 | 总收益 | 基准收益 | 超额收益 | Calmar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dividend Quality V1 | -2.54% | -72.49% | 0.09 | 20.53% | 5 | 0 | 0.22% | -24.70% | 63.12% | -87.82% | -0.04 |
| Quality Alpha V1 | 11.86% | -51.66% | 0.58 | 529.75% | 2841 | 204 | 13.52% | 244.29% | 63.12% | 181.17% | 0.23 |

## 行业分布

| industry_level1 | 持仓记录数 | 占比 |
| --- | --- | --- |
| 未知 | 40 | 1.0 |

## 市值分布

| market_cap_bucket | 持仓记录数 | 占比 |
| --- | --- | --- |
| 未知 | 40 | 1.0 |

## 最新一期持仓

| rank | symbol | name | dividend_yield_proxy | payout_ratio | roe | roa | ocf_to_or | debt_to_assets | industry_level1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 002423.SZ | 中粮资本 | 0.56% | 11.01% | 5.69 | 1.60 | 25.52 | 76.36 | 未知 |

## 归因判断

当前 V1 不构成可上线策略：分红代理覆盖过低，组合长期不足20只，更像是在验证数据缺口，而不是验证稳定红利因子。

当前结果不能证明收益来自红利或质量。若后续补齐标准分红实施表，再重新验证
trailing dividend yield、连续分红和支付率，才适合判断红利质量因子是否有效。

## 风险与后续

- 标准分红明细表缺失，无法验证真实除权除息口径、连续分红和滚动股息率。
- `comshare_payable_dvd/div_payt` 来自财报科目，覆盖低且存在会计口径和单位口径偏差。
- 行业覆盖仍依赖项目内置行业映射，未知行业可能影响行业暴露判断。
- 下一步应优先补齐标准 `dividend` / 分红实施公告表，再升级 Dividend Quality V2。
