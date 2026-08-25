# Industry Chain Stock Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and compare three stock-selection strategies: single-chain semiconductor selection, multi-chain competition, and whole-pool momentum selection.

**Architecture:** Add a focused chain-stock module that owns stock pools, scoring, and target-weight signal generation. Add an example runner that fetches cached K-line data, runs the three strategies, compares them with the Shanghai Composite benchmark, and optionally records history.

**Tech Stack:** Python, pandas, existing BacktestEngine target-weight execution, existing OHLCV SQLite cache, pytest.

---

### Task 1: Chain Stock Pool And Selector

**Files:**
- Create: `backtest/chain_selection.py`
- Test: `tests/test_chain_selection.py`

- [ ] Write failing tests for stock scoring, chain gating, multi-chain selection, and whole-pool selection.
- [ ] Run `pytest tests/test_chain_selection.py -q` and verify failures.
- [ ] Implement `ChainStock`, `ChainDefinition`, `ChainStockSelectionStrategy`.
- [ ] Run `pytest tests/test_chain_selection.py -q` and verify pass.

### Task 2: ABC Comparison Runner

**Files:**
- Create: `examples/compare_chain_stock_selection.py`
- Test: `tests/test_chain_stock_selection_example.py`

- [ ] Write failing tests for formatting and demo ABC comparison.
- [ ] Run `pytest tests/test_chain_stock_selection_example.py -q` and verify failures.
- [ ] Implement demo and real-data runner using cached Tencent K-line data.
- [ ] Run `pytest tests/test_chain_stock_selection_example.py -q` and verify pass.

### Task 3: Real Backtest And Verification

**Files:**
- Modify only if tests expose integration issues.

- [ ] Run focused tests.
- [ ] Run full `pytest`.
- [ ] Run `python examples/compare_chain_stock_selection.py --days 730`.
- [ ] Summarize ABC returns, drawdowns, and excess returns versus Shanghai Composite.
