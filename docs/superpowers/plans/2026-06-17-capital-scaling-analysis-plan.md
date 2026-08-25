# Capital Scaling Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 评估系统在 10万、50万、100万、500万资金规模下的可扩展性、稳定性与可交易性边界。

**Architecture:** 新增 `backtest/capital_scaling.py`，独立实现资本规模模拟、流动性压力测试、执行成本曲线、组合脆弱性和 scaling stability 分析。只消费组合权重、收益序列和行情成交额数据，不修改 M0 ExecutionModel，不新增因子，不改变策略逻辑。

**Tech Stack:** Python dataclass、Pandas、pytest、标准库 math。

## Global Constraints

- 不允许修改 M0。
- 不允许新增因子。
- 不允许机器学习。
- 不允许优化收益。
- 不允许改变策略逻辑。

---

### Task 1: Capital Scaling Simulator

**Files:**
- Create: `backtest/capital_scaling.py`
- Test: `tests/test_capital_scaling.py`

**Interfaces:**
- Produces: `CapitalScalingSimulator.simulate(...) -> list[CapitalScalingResult]`

- [ ] **Step 1:** 写失败测试，覆盖 10万、50万、100万、500万输出 return/drawdown/turnover/execution cost。
- [ ] **Step 2:** 运行 `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_capital_scaling.py`，确认模块缺失失败。
- [ ] **Step 3:** 实现最小模拟器。
- [ ] **Step 4:** 重跑聚焦测试。

### Task 2: Liquidity, Cost Curve, Fragility, Stability

**Files:**
- Modify: `backtest/capital_scaling.py`
- Test: `tests/test_capital_scaling.py`

**Interfaces:**
- Produces: `LiquidityStressTester.run(...) -> LiquidityStressResult`
- Produces: `ExecutionCostCurve.analyze(...) -> ExecutionCostCurveResult`
- Produces: `PortfolioFragilityTester.run(...) -> dict[str, FragilityResult]`
- Produces: `ScalingStabilityAnalyzer.analyze(...) -> StabilityResult`

- [ ] **Step 1:** 写失败测试，覆盖不可交易股票比例和成交失败率。
- [ ] **Step 2:** 写失败测试，覆盖成本曲线 break point 判断。
- [ ] **Step 3:** 写失败测试，覆盖单标的、行业集中、市场极端冲击下回撤和 recovery time。
- [ ] **Step 4:** 写失败测试，覆盖 turnover stability、top holdings stability、signal consistency。
- [ ] **Step 5:** 实现最小分析类，并运行全量 pytest。
