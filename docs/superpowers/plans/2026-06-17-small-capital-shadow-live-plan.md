# Small Capital Shadow Live System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建不接券商下单的 Small Capital Shadow Live System，用真实日线行情驱动每日收盘后的信号、目标组合、调仓计划、约束检查、漂移控制和对账输出。

**Architecture:** 新增 `backtest/live_shadow.py`，作为 M4 live loop 层，消费注入式 data updater / signal generator / portfolio builder，不修改 M0 ExecutionModel，不新增因子，不接真实券商。M3 `paper_execution.py` 继续负责成交仿真，M4 负责准实盘日常流程和稳定性检查。

**Tech Stack:** Python dataclass、Pandas、pytest、标准库 typing。

## Global Constraints

- 不允许接券商真实交易接口。
- 不允许修改 M0 ExecutionModel。
- 不允许新增因子。
- 不允许机器学习。
- 不允许优化收益。
- 不允许回测替代实盘逻辑。

---

### Task 1: Live Data Loop And Rebalance Plan

**Files:**
- Create: `backtest/live_shadow.py`
- Test: `tests/test_live_shadow.py`

**Interfaces:**
- Produces: `LiveDataLoop.run_daily(trade_date: str) -> DailyLiveResult`
- Consumes: injected `data_updater`, `signal_generator`, `portfolio_builder`

- [ ] **Step 1:** Write failing test for daily loop generating signal, target portfolio, and rebalance plan.
- [ ] **Step 2:** Run `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_live_shadow.py`.
- [ ] **Step 3:** Implement minimal `LiveDataLoop`, `DailyLiveResult`, and `RebalancePlan`.
- [ ] **Step 4:** Re-run focused test.

### Task 2: Market Constraints, Drift, Reconciliation, Capital Controls

**Files:**
- Modify: `backtest/live_shadow.py`
- Test: `tests/test_live_shadow.py`

**Interfaces:**
- Produces: `MarketConstraintChecker.check_plan(...)`
- Produces: `PortfolioDriftSystem.analyze(...)`
- Produces: `DailyReconciliation.reconcile(...)`
- Produces: `CapitalConstraint.apply(...)`

- [ ] **Step 1:** Add failing tests for limit up/down, suspended, liquidity, T+1 pending confirmation.
- [ ] **Step 2:** Add failing tests for drift threshold trigger and daily reconciliation breakdown.
- [ ] **Step 3:** Add failing tests for fixed capital, max symbol weight, and cash ratio.
- [ ] **Step 4:** Implement minimal classes and rerun focused tests.
- [ ] **Step 5:** Run `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest`.
