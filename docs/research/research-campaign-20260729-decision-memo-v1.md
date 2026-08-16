# 2026-07-29策略研究决策备忘录 V1

## 决策

`KEEP_PRODUCTION_UNCHANGED_NO_NEW_STRATEGY`

- 生产策略未修改；scheduler未修改。
- 批次共 71 项，其中策略候选
  20 个，新增晋级
  0 个。

## A股因子证据

- 31个家族验证期正收益比例：
  93.5%；锁定期：
  25.8%。
- 验证期核心通过者的锁定失效率：
  100.0%；锁定核心通过：
  0。
- 中证500相对沪深300价差对共同超额的解释度：
  86.5%；高相关组相对低相关组的
  持仓底部半数占比差：
  39.9%。
- 剥离中盘风格后的走步残差门槛通过：
  0。
- 低换手相对高换手的锁定收益中位优势：
  9.15%；
  Bootstrap为正概率：
  83.4%；
  置换p值：0.0103。
- 低换手优势不建立Alpha：
  True。

## 纳指黄金与执行风险

- 159941容量持续恢复起点：
  20230228。
- 容量恢复后相对场内标普年化收益差：
  7.41%；
  回撤改善：7.77%。
- 159941最新同日净值溢价：
  11.01%；
  两个月中位：8.74%。
- 按组合60%权重完全归一化冲击：
  -5.95%。
- 境内同标的ETF扫描：12只；
  当前执行门槛通过：0只；
  横截面溢价中位：9.43%，
  超过5%占比：100.0%。

## 新候选结果

- 日内强度减隔夜情绪全期年化：
  -21.19%；
  回撤：-97.38%。
- 分类：`ROBUST_ECONOMIC_SIGN_FAILURE_NOT_COST_ARTIFACT`。

## 标普500场内执行证据

- 当前执行门槛通过：1只，即
  `513650.SH`；最新同日净值溢价：
  4.67%。
- 与513500在803个共同交易日的日收益相关：
  0.9544；Beta：
  0.9403；累计收益差：
  -3.52%。
- 等价性分类：`INSTRUMENT_RETURN_EQUIVALENCE_FAILED`；允许替换：
  False。
- 单位净值日收益相关：
  0.9998；净值Beta：
  0.9970；净值年化跟踪误差：
  0.30%。
- 场内主动收益与溢价变化差相关：
  0.9984；
  说明底层净值高度一致，但场内溢价路径仍使直接替换不成立。
- 513650当前溢价处于自身历史分位：
  92.9%。
- 513500历史溢价至少5%时，未来20日溢价效应中位：
  -1.23%；
  负效应概率：
  74.2%。
- 月度聚类Bootstrap中位为负概率：
  100.0%；
  19个非重叠事件中位效应：
  -0.70%，负效应频率：
  57.9%。

## 标普黄金波动目标候选

- OOS年化/Sharpe/回撤：
  15.28% /
  1.261 /
  -20.31%。
- 相对同波动目标标普收益提升：
  3.06%。
- 回撤门槛短缺：0.31%；
  年换手：1.62x，超限：
  0.12x。
- 分类：`CONCENTRATED_BORDERLINE_REJECTION`；来源决策：
  `REJECTED`，不晋级。
- Bootstrap收益/Sharpe/回撤优势概率：
  78.5% /
  90.0% /
  86.2%；
  滚动三年收益提升为正占比：
  69.2%。
- 统计分类：`INCONCLUSIVE`。

## 五资产独立趋势方向

- 数据门禁决策：`REJECTED_BEFORE_BACKTEST`；分类：
  `LOCAL_INCREMENT_GAP_UPSTREAM_AVAILABLE`。
- 本地增量缺失：4行；
  {'159915.SZ': ['20260727', '20260728'], '510500.SH': ['20260727', '20260728']}。
- 策略回测已运行：False。

## 交易活跃度稳定性因子

- 数据门禁通过：True；策略决策：
  `REJECTED`。
- 全期年化/Sharpe/回撤：
  12.34% /
  0.617 /
  -38.92%。
- 年换手/累计成本影响：
  18.24x /
  67.40%。
- 2024至今/最新年年化：
  6.32% /
  -18.97%；
  与质量策略相关：0.7546。
- 分类：`BROAD_RISK_TURNOVER_AND_RECENT_RETURN_FAILURE`；运行变体：
  False。

## 决策链检查

- PASS：campaign_has_zero_new_strategy_promotions
- PASS：campaign_current_execution_risks_open
- PASS：no_factor_family_passes_locked_core_gate
- PASS：midcap_common_mode_confirmed
- PASS：holdings_support_midcap_exposure
- PASS：no_factor_passes_style_residual_gate
- PASS：lower_turnover_does_not_establish_alpha
- PASS：capacity_recovery_does_not_remove_historical_bias
- PASS：current_nasdaq_premium_exceeds_10pct
- PASS：no_execution_feasible_nasdaq100_alternative
- PASS：nasdaq100_premium_is_cross_fund_common_mode
- PASS：sp500_has_one_currently_feasible_instrument
- PASS：sp500_candidate_is_not_treated_as_equivalent_replacement
- PASS：sp500_price_divergence_is_attributed_without_authorizing_replacement
- PASS：sp500_high_premium_normalization_risk_is_preserved
- PASS：sp500_normalization_risk_survives_overlap_controls
- PASS：sp500_gold_borderline_candidate_remains_rejected
- PASS：sp500_gold_statistics_do_not_override_rejection
- PASS：independent_trend_is_blocked_before_backtest_by_local_data_gap
- PASS：trading_activity_strategy_is_robustly_closed_without_variants
- PASS：intraday_candidate_robustly_rejected

本备忘录只汇总已登记的结构化研究证据，不重算收益、不调整策略、
不启停scheduler，也不构成实盘下单指令。
