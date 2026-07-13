# Operations Review Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only operations review metrics that connect current decisions, acknowledgement records, and closure status.

**Architecture:** Build `runtime.operations_review` as a pure aggregation layer over `operations_decision` and `operations_ack`. Expose it through a lightweight FastAPI route and render a compact review panel on the scheduler page.

**Tech Stack:** Python 3, SQLite, FastAPI, React + TypeScript + Vite.

## Global Constraints

- 不运行策略、不运行 Tushare、不发送 Bark。
- 不接券商、不自动下单，所有处置仍为人工确认。
- 只读已有运行事实和确认记录，不写入新的运行数据。
- `api/service.py` 已接近 500 行，本阶段不修改它。
- 新行为必须先写失败测试，再实现。

---

### Task 1: Runtime Review Metrics

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/operations_review.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_review.py`

**Interfaces:**
- Consumes: `build_operations_decision(repo_root: Path, readiness: Mapping[str, object] | None = None)`
- Consumes: `list_operations_ack(db_path: Path, limit: int = 20)`
- Produces: `build_operations_review(repo_root: Path, db_path: Path, readiness: Mapping[str, object] | None = None) -> dict[str, object]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_operations_review.py`:

```python
from pathlib import Path

from runtime.operations_ack import record_operations_ack
from runtime.operations_review import build_operations_review


def _seed_warning(root: Path) -> None:
    (root / "runs" / "20260703").mkdir(parents=True)


def test_operations_review_marks_open_when_actions_have_no_ack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BARK_URL", raising=False)
    _seed_warning(tmp_path)
    db_path = tmp_path / "state" / "system_state.sqlite"
    readiness = {"status": "READY", "checks": []}

    review = build_operations_review(tmp_path, db_path, readiness)

    assert review["closure_status"] == "OPEN"
    assert review["current_action_count"] > 0
    assert review["unacknowledged_action_count"] > 0
    assert review["acknowledged_action_count"] == 0


def test_operations_review_marks_closed_when_current_action_is_acknowledged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BARK_URL", raising=False)
    _seed_warning(tmp_path)
    db_path = tmp_path / "state" / "system_state.sqlite"
    record_operations_ack(
        db_path,
        {
            "trade_date": "20260703",
            "source": "operations_observation",
            "category": "run_artifacts",
            "name": "daily_report.md",
            "severity": "WARNING",
            "decision": "ACTION_REQUIRED",
            "message": "run_artifacts.daily_report.md 状态为 WARN",
            "resolution": "已确认盘前活动不需要日报",
            "operator": "admin",
        },
    )
    readiness = {"status": "READY", "checks": []}

    review = build_operations_review(tmp_path, db_path, readiness)

    assert review["closure_status"] == "OPEN"
    assert review["acknowledged_action_count"] == 1
    assert review["unacknowledged_action_count"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_review.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement metrics**

Create a focused module that returns:
- `closure_status`: `CLOSED` when no current actions or every current action has a matching acknowledgement, otherwise `OPEN`;
- `current_action_count`;
- `acknowledged_action_count`;
- `unacknowledged_action_count`;
- `acknowledgement_count`;
- `latest_ack_at`;
- `latest_decision`;
- `unacknowledged_actions`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_review.py -q`

Expected: `2 passed`.

### Task 2: Local API Route

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/api/local_server.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_review_api.py`

**Interfaces:**
- Produces: `GET /api/operations/review`

- [ ] **Step 1: Write failing API test**

Create `tests/test_operations_review_api.py`:

```python
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_review_api_returns_closure_metrics(tmp_path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.get("/api/operations/review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["closure_status"] in {"OPEN", "CLOSED"}
    assert "current_action_count" in payload
    assert "acknowledgement_count" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_review_api.py -q`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement route**

Import `build_operations_review` in `api/local_server.py`; use `api_service.paths.root`, `api_service.paths.system_state_path`, and `api_service.readiness()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_review_api.py -q`

Expected: `1 passed`.

### Task 3: Frontend Review Panel

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/reviewModel.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/reviewApi.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/reviewStatus.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/reviewStatus.test.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/types.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/loadDashboardData.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/pages/scheduler/SchedulerPage.tsx`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/shared/styles/acknowledgement.css`

**Interfaces:**
- Consumes: `GET /api/operations/review`
- Produces: scheduler page review metrics panel.

- [ ] **Step 1: Write failing frontend test**

Create `frontend/src/entities/operations/reviewStatus.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { reviewStatusTitle, reviewStatusTone } from "./reviewStatus";

describe("operations review status helpers", () => {
  it("maps closure status to dashboard labels", () => {
    expect(reviewStatusTitle("CLOSED")).toBe("闭环完成");
    expect(reviewStatusTitle("OPEN")).toBe("仍需跟进");
    expect(reviewStatusTone("CLOSED")).toBe("success");
    expect(reviewStatusTone("OPEN")).toBe("warning");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- operations/reviewStatus`

Expected: FAIL because `reviewStatus` does not exist.

- [ ] **Step 3: Implement frontend integration**

Add typed API client, load review metrics with dashboard data, and render the panel below the operations decision panel.

- [ ] **Step 4: Run frontend operations tests**

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
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_review.py tests/test_operations_review_api.py tests/test_operations_ack.py tests/test_operations_ack_api.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
./scripts/restart_services.sh
```

- [ ] **Step 2: Update planning state**

Mark E18.1 done and set next action to E19 after verification passes.

- [ ] **Step 3: Stage safely**

Stage only source, test, frontend, plan, and `.planning` files. Exclude `runs/`, `reports/`, `runtime_backups/`, DuckDB, SQLite, and logs.

- [ ] **Step 4: Commit**

Run: `git commit -m "feat: add operations review metrics"`

## Self-Review

- Spec coverage: E18 connects decision actions, acknowledgement records, and closure status.
- Placeholder scan: no TBD/TODO/implement-later placeholders.
- Type consistency: backend and frontend both use `closure_status`, action counts, acknowledgement counts, and `latest_decision`.
