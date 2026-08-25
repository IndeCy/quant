# Operations Alert Decision Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only operations decision surface that answers whether the user needs manual intervention today.

**Architecture:** Add `runtime.operations_decision` as a thin aggregation layer over existing operations observation and readiness facts. Expose it through the local API and render it on the scheduler page so daily review starts from actionability, not scattered files.

**Tech Stack:** Python 3, FastAPI, existing runtime repositories, React + TypeScript + Vite.

## Global Constraints

- 不修改策略逻辑，不运行 Tushare 更新，不运行策略，不发送 Bark。
- 只读已有 `runs/`、`state/`、`logs/`、`reports/` 和现有 API 事实源。
- 保持单文件不超过 500 行。
- 手工干预建议必须是人工确认，不自动下单。
- 新行为必须先写失败测试，再实现。

---

### Task 1: Runtime Decision Model

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/operations_decision.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_decision.py`

**Interfaces:**
- Consumes: `build_operations_observation(repo_root: Path) -> dict[str, object]`
- Produces: `build_operations_decision(repo_root: Path, readiness: Mapping[str, object] | None = None) -> dict[str, object]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_operations_decision.py`:

```python
from pathlib import Path

from runtime.operations_decision import build_operations_decision


def _seed_complete_run(root: Path) -> None:
    run_dir = root / "runs" / "20260702"
    run_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv", "run_log.txt"]:
        (run_dir / name).write_text("ok", encoding="utf-8")
    (root / "state").mkdir()
    (root / "state" / "scheduler.heartbeat").write_text("ok", encoding="utf-8")
    (root / "state" / "scheduler.sqlite").write_text("", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "scheduler.log").write_text("ok", encoding="utf-8")
    (root / "reports").mkdir()
    for name in ["dashboard.html", "dashboard_data.json", "quality_overlay_paper_latest.md"]:
        (root / "reports" / name).write_text("ok", encoding="utf-8")


def test_operations_decision_reports_no_action_when_all_inputs_pass(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BARK_URL", "https://api.day.app/key")
    _seed_complete_run(tmp_path)
    readiness = {"status": "READY", "checks": [{"name": "scheduler_job", "status": "PASS", "message": "ok"}]}

    decision = build_operations_decision(tmp_path, readiness)

    assert decision["decision"] == "NO_ACTION"
    assert decision["severity"] == "NORMAL"
    assert decision["manual_intervention_required"] is False
    assert decision["latest_run_date"] == "20260702"
    assert decision["actions"] == []


def test_operations_decision_requires_action_for_failures(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BARK_URL", raising=False)
    (tmp_path / "runs" / "20260703").mkdir(parents=True)
    readiness = {"status": "NOT_READY", "checks": [{"name": "scheduler_job", "status": "FAIL", "message": "每日任务未登记"}]}

    decision = build_operations_decision(tmp_path, readiness)

    assert decision["decision"] == "ACTION_REQUIRED"
    assert decision["severity"] == "CRITICAL"
    assert decision["manual_intervention_required"] is True
    assert any(action["source"] == "readiness" for action in decision["actions"])
    assert any(action["source"] == "operations_observation" for action in decision["actions"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_decision.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'runtime.operations_decision'`.

- [ ] **Step 3: Write minimal implementation**

Create `runtime/operations_decision.py` with a small pure function:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from runtime.operations_observation import build_operations_observation


def build_operations_decision(repo_root: Path, readiness: Mapping[str, object] | None = None) -> dict[str, object]:
    ...
```

The implementation should:
- classify FAIL readiness checks as `CRITICAL`;
- classify observation WARN/FAIL as `WARNING`/`CRITICAL`;
- return `NO_ACTION` only when no actions exist;
- include `latest_run_date`, `latest_activity_date`, summary counts, and action list.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_decision.py -q`

Expected: `2 passed`.

### Task 2: Local API Endpoint

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/api/service.py`
- Modify: `/Users/admin/PycharmProjects/quant/api/local_server.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_decision_api.py`

**Interfaces:**
- Consumes: `build_operations_decision(...)`
- Produces: `GET /api/operations/decision`

- [ ] **Step 1: Write the failing test**

Create `tests/test_operations_decision_api.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_decision_api_returns_actionable_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BARK_URL", "https://api.day.app/key")
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    run_dir = paths.runs_dir / "20260702"
    run_dir.mkdir(parents=True)
    for name in ["daily_report.md", "strategy_metrics.json", "portfolio_snapshot.csv", "rebalance_plan.csv", "run_log.txt"]:
        (run_dir / name).write_text("ok", encoding="utf-8")

    client = TestClient(create_app(LocalApiService(paths)))
    response = client.get("/api/operations/decision")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] in {"NO_ACTION", "ACTION_REQUIRED"}
    assert "manual_intervention_required" in payload
    assert "actions" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_decision_api.py -q`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement endpoint**

Add `LocalApiService.operations_decision()` and route `GET /api/operations/decision`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_decision_api.py -q`

Expected: `1 passed`.

### Task 3: Scheduler Page Decision Panel

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/decisionModel.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/decisionApi.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/decisionStatus.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/decisionStatus.test.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/types.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/loadDashboardData.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/pages/scheduler/SchedulerPage.tsx`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/shared/styles/operations.css`

**Interfaces:**
- Consumes: `GET /api/operations/decision`
- Produces: scheduler page panel for decision, severity, next action, and action rows.

- [ ] **Step 1: Write the failing frontend test**

Create `frontend/src/entities/operations/decisionStatus.test.ts`:

```typescript
import { decisionTone, decisionTitle } from "./decisionStatus";

describe("operations decision status helpers", () => {
  it("maps decision state to Chinese dashboard labels", () => {
    expect(decisionTitle("NO_ACTION")).toBe("今日无需人工处理");
    expect(decisionTitle("ACTION_REQUIRED")).toBe("需要人工处理");
    expect(decisionTone("CRITICAL")).toBe("danger");
    expect(decisionTone("WARNING")).toBe("warning");
    expect(decisionTone("NORMAL")).toBe("success");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- operations/decisionStatus`

Expected: FAIL because `decisionStatus` does not exist.

- [ ] **Step 3: Implement frontend entity and page panel**

Add typed API client, load decision in `loadDashboardData`, add `operationsDecision` to `DashboardData`, and render a compact decision panel above the observation panel.

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- operations`

Expected: all operations tests pass.

### Task 4: Verification, Governance, Commit

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/.planning/STATE.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/ROADMAP.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/TASKS.md`

**Interfaces:**
- Produces: E16 completion state and next E17 placeholder.

- [ ] **Step 1: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_decision.py tests/test_operations_decision_api.py tests/test_operations_observation.py tests/test_operations_observation_api.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
./scripts/restart_services.sh
```

- [ ] **Step 2: Update planning state**

Mark E16.1 done and set next action to E17 only after verification passes.

- [ ] **Step 3: Stage safely**

Stage only source, test, frontend, plan, and `.planning` files. Do not stage `runs/`, `reports/`, `runtime_backups/`, DuckDB, SQLite, or logs.

- [ ] **Step 4: Commit**

Run: `git commit -m "feat: add operations alert decision surface"`

Expected: commit succeeds.

## Self-Review

- Spec coverage: plan covers actionability, API visibility, frontend visibility, no task execution, no notifications, manual-only boundary.
- Placeholder scan: no TBD/TODO/implement-later placeholders.
- Type consistency: Python returns `decision`, `severity`, `manual_intervention_required`, `actions`; frontend model uses the same names.
