# Paper Trading System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建轻量 Paper Trading / Shadow Trading 执行仿真层，用于比较回测目标权重与真实执行条件下的模拟盘差异。

**Architecture:** 新增 `backtest/paper_execution.py`，独立承载 `PaperTradingEngine`、`BrokerSimulator`、`OrderManager`、`PortfolioTracker`、`DriftAnalyzer`。不修改 M0 `ExecutionModel`，不改因子和策略逻辑，只消费 signal/target weights 与已有日线行情 mock 数据。

**Tech Stack:** Python dataclass、Pandas、标准库 typing，pytest 单测。

---

### Task 1: Paper Trading Core Interfaces

**Files:**
- Create: `backtest/paper_execution.py`
- Test: `tests/test_paper_execution.py`

- [ ] **Step 1: Write failing tests**

```python
def test_signal_delay_test():
    engine = PaperTradingEngine(...)
    result = engine.run_signals(...)
    assert result.orders[0].execute_date == "2024-01-03"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_paper_execution.py`

Expected: FAIL because `backtest.paper_execution` does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement dataclasses for order, execution, portfolio snapshot, broker config, and the five required classes.

- [ ] **Step 4: Run focused tests**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_paper_execution.py`

Expected: PASS.

### Task 2: Milestone 3 Verification

**Files:**
- Modify: `tests/test_paper_execution.py`

- [ ] **Step 1: Cover required verification tests**

Add tests for signal delay, limit up/down execution failure, slippage sensitivity, backtest vs paper comparison, and turnover deviation.

- [ ] **Step 2: Run full test suite**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest`

Expected: all tests pass.
