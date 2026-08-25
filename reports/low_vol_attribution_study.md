# Low Vol Attribution Study

- 数据：`daily_adj_19901219_20260615.duckdb` + `fina_indicator.duckdb`
- 财务可见性：使用 `ann_date <= signal_date` 的 as-of 口径
- 组合：月末全市场可投股票中，60日收益标准差最低20只

## 组合平均质量指标

| metric | low_vol | market | spread_low_vol_minus_market |
| --- | --- | --- | --- |
| debt_to_assets | 62.61 | 42.42 | 20.19 |
| grossprofit_margin | 32.05 | 29.48 | 2.57 |
| roa | 4.44 | 3.16 | 1.27 |
| roe | 6.22 | 3.21 | 3.01 |
| tr_yoy | 10.17 | 62.36 | -52.18 |

## 收益与波动

| bucket | annual_return | realized_vol |
| --- | --- | --- |
| low_vol | 2.47% | 18.34% |
| market | 4.41% | 27.84% |
| excess | -5.63% | 18.53% |

## 归因判断

- 质量暴露得分：0.60
- 结论：B. 主要来自高质量公司暴露
