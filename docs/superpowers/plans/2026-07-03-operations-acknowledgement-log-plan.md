# Operations Acknowledgement Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist manual acknowledgement and resolution records for operations alerts so Shadow Live decisions are auditable.

**Architecture:** Add a small SQLite-backed acknowledgement module that writes to the existing system state database. Expose read/write endpoints from the local FastAPI app without growing `api/service.py`, then render recent acknowledgements on the scheduler page beside the operations decision panel.

**Tech Stack:** Python 3, SQLite, FastAPI, React + TypeScript + Vite.

## Global Constraints

- 不运行策略、不运行 Tushare、不发送 Bark。
- 不接券商、不自动下单，所有处置均为人工确认记录。
- 使用现有 `state/system_state.sqlite`，不引入新数据库服务。
- `api/service.py` 已接近 500 行，本阶段不继续向其中添加方法。
- 新行为必须先写失败测试，再实现。

---

### Task 1: Runtime Acknowledgement Store

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/operations_ack.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_ack.py`

**Interfaces:**
- Produces: `record_operations_ack(db_path: Path, payload: Mapping[str, object]) -> dict[str, object]`
- Produces: `list_operations_ack(db_path: Path, limit: int = 20) -> list[dict[str, object]]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_operations_ack.py`:

```python
from pathlib import Path

from runtime.operations_ack import list_operations_ack, record_operations_ack


def test_record_operations_ack_persists_manual_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "system_state.sqlite"

    ack = record_operations_ack(
        db_path,
        {
            "trade_date": "20260703",
            "source": "readiness",
            "category": "scheduler",
            "name": "scheduler_job",
            "severity": "CRITICAL",
            "decision": "ACTION_REQUIRED",
            "message": "每日任务未登记",
            "resolution": "已重新登记调度",
            "operator": "admin",
        },
    )

    records = list_operations_ack(db_path)
    assert ack["ack_id"] == records[0]["ack_id"]
    assert records[0]["status"] == "ACKNOWLEDGED"
    assert records[0]["resolution"] == "已重新登记调度"


def test_record_operations_ack_rejects_missing_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "system_state.sqlite"

    try:
        record_operations_ack(db_path, {"trade_date": "20260703"})
    except ValueError as exc:
        assert "source, category and name are required" in str(exc)
    else:
        raise AssertionError("missing identity should fail")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_ack.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement module**

Create a focused module that lazily creates table `operations_acknowledgements`, validates action identity, inserts a row with status `ACKNOWLEDGED`, and lists recent rows ordered by `created_at DESC`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_ack.py -q`

Expected: `2 passed`.

### Task 2: Local API Routes

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/api/local_server.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_ack_api.py`

**Interfaces:**
- Consumes: `record_operations_ack(...)`, `list_operations_ack(...)`
- Produces: `GET /api/operations/acknowledgements`
- Produces: `POST /api/operations/acknowledgements`

- [ ] **Step 1: Write failing API test**

Create `tests/test_operations_ack_api.py`:

```python
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_ack_api_records_and_lists_acknowledgement(tmp_path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.post(
        "/api/operations/acknowledgements",
        json={
            "trade_date": "20260703",
            "source": "operations_observation",
            "category": "scheduler",
            "name": "heartbeat",
            "severity": "WARNING",
            "decision": "ACTION_REQUIRED",
            "message": "heartbeat 状态为 WARN",
            "resolution": "已确认 scheduler 正常运行",
            "operator": "admin",
        },
    )

    assert response.status_code == 200
    records = client.get("/api/operations/acknowledgements").json()
    assert records[0]["name"] == "heartbeat"
    assert records[0]["status"] == "ACKNOWLEDGED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_ack_api.py -q`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement routes**

Import the ack functions in `api/local_server.py`; use `api_service.paths.system_state_path` as the database path. Do not modify `api/service.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_ack_api.py -q`

Expected: `1 passed`.

### Task 3: Frontend Scheduler Acknowledgement Panel

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/ackModel.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/ackApi.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/ackStatus.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/ackStatus.test.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/types.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/loadDashboardData.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/pages/scheduler/SchedulerPage.tsx`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/shared/styles/acknowledgement.css`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET/POST /api/operations/acknowledgements`
- Produces: a recent acknowledgement list and a one-click acknowledgement button for current decision actions.

- [ ] **Step 1: Write failing frontend test**

Create `frontend/src/entities/operations/ackStatus.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { ackStatusTone } from "./ackStatus";

describe("operations acknowledgement status helpers", () => {
  it("maps acknowledgement status to dashboard tone", () => {
    expect(ackStatusTone("ACKNOWLEDGED")).toBe("success");
    expect(ackStatusTone("RESOLVED")).toBe("success");
    expect(ackStatusTone("UNKNOWN")).toBe("neutral");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- operations/ackStatus`

Expected: FAIL because `ackStatus` does not exist.

- [ ] **Step 3: Implement frontend entity and panel**

Add typed API calls, load acknowledgement records with dashboard data, render recent records, and add “记录已确认” buttons for decision actions. Use a new CSS file so `operations.css` remains under 500 lines.

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- operations`

Expected: operations tests pass.

### Task 4: Verification and Commit

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/.planning/STATE.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/ROADMAP.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/TASKS.md`

- [ ] **Step 1: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_ack.py tests/test_operations_ack_api.py tests/test_operations_decision.py tests/test_operations_decision_api.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
./scripts/restart_services.sh
```

- [ ] **Step 2: Update planning state**

Mark E17.1 done and set next action to E18 after verification passes.

- [ ] **Step 3: Stage safely**

Stage only source, test, frontend, plan, and `.planning` files. Exclude `runs/`, `reports/`, `runtime_backups/`, DuckDB, SQLite, and logs.

- [ ] **Step 4: Commit**

Run: `git commit -m "feat: add operations acknowledgement log"`

## Self-Review

- Spec coverage: E17 records manual acknowledgement, exposes API, displays recent records, and preserves no-auto-trading boundary.
- Placeholder scan: no TBD/TODO/implement-later placeholders.
- Type consistency: `ack_id`, `trade_date`, `source`, `category`, `name`, `severity`, `decision`, `message`, `resolution`, `operator`, `status` are used consistently across backend and frontend.
