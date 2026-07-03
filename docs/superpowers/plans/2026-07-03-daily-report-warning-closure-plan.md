# Daily Report Warning Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove false daily-report warnings by separating complete post-close run directories from pre-market or execution-check-only run directories.

**Architecture:** Update `runtime/operations_observation.py` so it exposes both `latest_activity_date` and `latest_complete_run_date`. Artifact checks should target the latest complete post-close run, while incomplete newer activity is surfaced separately as context, not as a warning against the daily report pipeline.

**Tech Stack:** Python standard library, pytest.

## Global Constraints

- 不修改策略、因子、执行模型或调仓逻辑。
- 不运行 Tushare 更新，不运行策略，不发送 Bark。
- 不提交 `runs/`、`reports/dashboard*`、DuckDB/SQLite、日志、runtime backup。
- 新增或变更核心逻辑先写失败测试，再实现。
- 生成 JSON 使用紧凑格式，避免生成文件超过 500 行。

---

### Task 1: Distinguish Complete Runs from Activity Runs

**Files:**
- Modify: `tests/test_operations_observation.py`
- Modify: `runtime/operations_observation.py`

**Interfaces:**
- Updates: `build_operations_observation(repo_root: Path) -> dict[str, object]`
- Adds field: `latest_activity_date`
- Keeps field: `latest_run_date` as alias for latest complete post-close run
- Adds field: `latest_activity_type`

- [ ] **Step 1: Write failing test**

Create a temp repo with `runs/20260702` containing full post-close artifacts and `runs/20260703` containing only `pre_market_check.md`. Assert latest complete run remains `20260702`, latest activity is `20260703`, and daily report artifact is PASS.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py -q`

Expected: FAIL because current code uses the latest date directory for daily artifacts.

- [ ] **Step 3: Implement classification**

Add helpers that classify a run directory as `complete_daily_run`, `pre_market_only`, or `partial_activity`. Daily artifact checks use latest `complete_daily_run`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py -q`

Expected: PASS.

### Task 2: Regenerate Summary and Update Governance

**Files:**
- Modify: `docs/release/operations_observation_summary.md`
- Modify: `docs/release/operations_observation_summary.json`
- Modify: `.planning/STATE.md`
- Modify: `.planning/ROADMAP.md`
- Modify: `.planning/TASKS.md`

- [ ] **Step 1: Generate current summary**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_operations_observation.py --output-dir docs/release`

Expected: latest complete run points to the latest directory with full daily artifacts, while `20260703` appears as latest activity if it only has pre-market files.

- [ ] **Step 2: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation.py tests/test_post_baseline_audit.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit source/governance outputs only**

Stage only E14 source, tests, docs, planning files, and release summary. Do not commit `runs/` or dashboard report mutations.

## Self-Review

- Spec coverage: closes the exact WARN source from E13 without changing runtime behavior.
- Placeholder scan: no TBD or vague commands remain.
- Type consistency: new field names are defined before use.
