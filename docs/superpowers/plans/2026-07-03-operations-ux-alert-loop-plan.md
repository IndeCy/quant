# Operations UX and Alert Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the operations observation summary in the local API and scheduler page so daily review no longer requires manually opening release Markdown files.

**Architecture:** Reuse `runtime.operations_observation.build_operations_observation` as the single source of truth. Add a read-only API endpoint, a small frontend entity module, and a scheduler-page panel that displays latest complete run, latest activity, scheduler evidence, notification evidence, and artifact status.

**Tech Stack:** FastAPI, Python standard library, pytest, React, TypeScript, Vitest.

## Global Constraints

- 不修改策略、因子、执行模型或调仓逻辑。
- 不运行 Tushare 更新，不运行策略，不发送 Bark。
- 不提交 `runs/`、`reports/dashboard*`、DuckDB/SQLite、日志、runtime backup。
- 后端新增测试不要继续写入接近 500 行的 `tests/test_local_api_service.py`。
- 前端新增模型放入 `frontend/src/entities/operations/`。
- 前端变更必须执行 `npm test` 和 `npm run build:pre`。
- `build:pre` 后必须重启本地服务。

---

### Task 1: Operations Observation API

**Files:**
- Modify: `api/service.py`
- Modify: `api/local_server.py`
- Create: `tests/test_operations_observation_api.py`

**Interfaces:**
- Produces: `LocalApiService.operations_observation() -> dict[str, Any]`
- Produces: `GET /api/operations/observation`

- [ ] **Step 1: Write failing API test**

Create a test using `TestClient(create_app(LocalApiService(paths)))` and assert `/api/operations/observation` returns `latest_run_date`, `latest_activity_date`, `summary`, and `ready_for_daily_review`.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation_api.py -q`

Expected: FAIL with 404 or missing method.

- [ ] **Step 3: Implement API**

Import `build_operations_observation` in `api/service.py`, add a small method, and add one FastAPI route in `api/local_server.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation_api.py -q`

Expected: PASS.

### Task 2: Frontend Data Model and Loader

**Files:**
- Create: `frontend/src/entities/operations/model.ts`
- Create: `frontend/src/entities/operations/api.ts`
- Create: `frontend/src/entities/operations/status.test.ts`
- Create: `frontend/src/entities/operations/status.ts`
- Modify: `frontend/src/app/types.ts`
- Modify: `frontend/src/app/loadDashboardData.ts`

**Interfaces:**
- Produces: `OperationsObservation`
- Produces: `getOperationsObservation(): Promise<OperationsObservation>`
- Produces: `observationStatusTone(status: string): string`

- [ ] **Step 1: Write failing frontend status test**

Assert `PASS -> success`, `WARN -> warning`, `FAIL -> danger`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- operations`

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement entity and loader wiring**

Add `operationsObservation` to `DashboardData` and fetch it in `loadDashboardData`.

- [ ] **Step 4: Run frontend test**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test`

Expected: PASS.

### Task 3: Scheduler Page Panel

**Files:**
- Modify: `frontend/src/pages/scheduler/SchedulerPage.tsx`
- Modify: `frontend/src/shared/styles/operations.css`

**Interfaces:**
- Consumes: `data.operationsObservation`

- [ ] **Step 1: Add observation panel**

Display summary counts, latest activity, latest complete run, run artifacts, scheduler evidence, notification status, and held reports.

- [ ] **Step 2: Build verify**

Run:

```bash
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
./scripts/restart_services.sh
```

Expected: PASS and local services restart.

### Task 4: Governance and Commit

**Files:**
- Modify: `.planning/STATE.md`
- Modify: `.planning/ROADMAP.md`
- Modify: `.planning/TASKS.md`

- [ ] **Step 1: Run backend verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_observation_api.py tests/test_operations_observation.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Commit source/governance only**

Stage E15 source/tests/docs/planning files only. Do not commit runtime `runs/` or dashboard report mutations.

## Self-Review

- Spec coverage: exposes observation summary in API and UI without changing execution behavior.
- Placeholder scan: no TBD or vague commands remain.
- Type consistency: output field names match existing `operations_observation` report.
