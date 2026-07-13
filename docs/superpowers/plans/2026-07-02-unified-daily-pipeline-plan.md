# Unified Daily Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduled runs, manual reruns, and API-triggered runs execute the same atomic daily trading pipeline.

**Architecture:** Add a single orchestrator in `runtime/daily_pipeline.py` that runs data update, data validation, strategy batch, run-step logging, and notification resolution. Scheduler and CLI entrypoints call the orchestrator through one command; legacy scripts stay available for internal compatibility but are no longer the scheduled business entry.

**Tech Stack:** Python 3, APScheduler, SQLite runtime repository, existing Bark notifier.

## Global Constraints

- Do not change strategy logic, factors, or risk parameters.
- Do not include the research monitor in the trading pipeline.
- Data update failure must stop strategy execution.
- Bark missing or failed delivery must be logged, not swallowed silently.
- Preserve existing user changes in the dirty worktree.

---

### Task 1: Add Unified Pipeline Orchestrator

**Files:**
- Create: `runtime/daily_pipeline.py`
- Create: `scripts/run_daily_pipeline.py`
- Modify: `runtime/notification_config.py`
- Test: `tests/test_daily_pipeline.py`

**Interfaces:**
- Produces: `run_production_daily_pipeline(paths: RuntimePaths | None = None, push: bool = False, source: str = "manual") -> dict[str, object]`
- Produces: `NotificationResult(status: str, message: str)`

- [ ] Write tests for success path, data failure stopping strategies, and missing Bark logging.
- [ ] Implement `runtime/daily_pipeline.py` using existing `scripts.run_daily_data_update.main` and `run_enabled_strategy_instances`.
- [ ] Add `scripts/run_daily_pipeline.py` with `--push` and `--source`.
- [ ] Run `pytest tests/test_daily_pipeline.py -q`.

### Task 2: Route Scheduler and API to the Single Entry

**Files:**
- Modify: `runtime/scheduler.py`
- Modify: `api/service.py`
- Test: `tests/test_runtime_scheduler.py`
- Test: `tests/test_local_api_service.py`

**Interfaces:**
- Consumes: `scripts/run_daily_pipeline.py --push --source scheduler`

- [ ] Update scheduler command builder to use `scripts/run_daily_pipeline.py`.
- [ ] Keep job IDs stable where possible for frontend compatibility.
- [ ] Update API manual trigger to call the same orchestrator.
- [ ] Run scheduler and API tests.

### Task 3: Verify Full Regression

**Files:**
- No production files unless tests reveal a Phase 1 pipeline issue.

- [ ] Run targeted tests for pipeline, scheduler, strategy batch, and local API.
- [ ] Run full `pytest -q`.
- [ ] Restart local services if scheduler command changed.
- [ ] Report exact behavior and remaining risks.
