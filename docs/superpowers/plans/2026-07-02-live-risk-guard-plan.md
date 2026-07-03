# Live Risk Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a low-frequency live risk workflow that separates strategy rebalance decisions from stop-loss/risk actions.

**Architecture:** Add a post-close `live_risk_guard` that reads monitoring metrics and emits risk actions, plus a next-morning `pre_market_check` that reads prior risk actions and creates an execution checklist for manual confirmation. Both are scheduled jobs with Bark notifications only when action is needed.

**Tech Stack:** Python 3, SQLite runtime state, existing monitoring repository, APScheduler, existing Bark notifier.

## Global Constraints

- Do not modify alpha strategy logic or parameters.
- Do not auto-submit broker orders.
- Do not introduce intraday real-time trading.
- Use existing monitoring data and local runtime storage.
- Notifications must distinguish rebalance action from risk action.

---

### Task 1: Post-Close Live Risk Guard

**Files:**
- Create: `runtime/live_risk_guard.py`
- Create: `scripts/run_live_risk_guard.py`
- Test: `tests/test_live_risk_guard.py`

**Interfaces:**
- Produces: `run_live_risk_guard(paths: RuntimePaths | None = None, trade_date: str | None = None, push: bool = False) -> RiskGuardResult`
- Produces files: `runs/YYYYMMDD/risk_guard_report.md`, `runs/YYYYMMDD/risk_actions.csv`

- [ ] Test normal state creates no notification and empty actions.
- [ ] Test critical daily loss/drawdown/high volatility writes risk action and sends Bark.
- [ ] Implement fixed thresholds: daily <= -5% warning, <= -8% critical; drawdown <= -10% warning, <= -20% critical; vol20 >= 50% high volatility.

### Task 2: Pre-Market Risk Check

**Files:**
- Create: `runtime/pre_market_check.py`
- Create: `scripts/run_pre_market_check.py`
- Test: `tests/test_pre_market_check.py`

**Interfaces:**
- Produces: `run_pre_market_check(paths: RuntimePaths | None = None, trade_date: str | None = None, previous_trade_date: str | None = None, push: bool = False) -> PreMarketCheckResult`
- Produces files: `runs/YYYYMMDD/pre_market_check.md`, `runs/YYYYMMDD/execution_checklist.csv`

- [ ] Test no previous risk actions means no Bark.
- [ ] Test previous critical action creates execution checklist and Bark.

### Task 3: Scheduler Integration

**Files:**
- Modify: `runtime/scheduler.py`
- Modify: tests for scheduler/API status.

**Interfaces:**
- Adds jobs: `pre_market_check_pipeline`, `live_risk_guard_pipeline`

- [ ] Schedule pre-market at 09:20.
- [ ] Schedule live risk guard at 16:55 after research monitor and before watchdog.
- [ ] Verify scheduler status includes both jobs.

### Task 4: Verification

**Files:**
- No production files unless tests expose issues.

- [ ] Run targeted tests.
- [ ] Run full pytest.
- [ ] Restart services and verify scheduler status.
- [ ] Run today's risk guard and pre-market check manually for acceptance.
