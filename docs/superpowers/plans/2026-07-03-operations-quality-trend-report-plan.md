# Operations Quality Trend Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate an indexed operations quality report so decision, acknowledgement, and closure metrics become part of the report system.

**Architecture:** Add a small `runtime.operations_quality_report` module that reads existing review metrics and acknowledgement records, writes Markdown/JSON artifacts under `reports/operations_quality/`, and registers the Markdown in `report_index`. Expose a read-only/generate endpoint from FastAPI without modifying `api/service.py`.

**Tech Stack:** Python 3, SQLite, FastAPI, existing report index, React report page.

## Global Constraints

- 不运行策略、不运行 Tushare、不发送 Bark。
- 不接券商、不自动下单。
- 不提交生成的 `reports/`、`runs/`、SQLite、DuckDB 或日志产物。
- `api/service.py` 已接近 500 行，本阶段不修改它。
- 新行为必须先写失败测试，再实现。

---

### Task 1: Operations Quality Report Writer

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/operations_quality_report.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_quality_report.py`

**Interfaces:**
- Consumes: `build_operations_review(repo_root: Path, db_path: Path, readiness: Mapping[str, object] | None = None)`
- Consumes: `list_operations_ack(db_path: Path, limit: int = 20)`
- Produces: `build_operations_quality_report(paths: RuntimePaths, readiness: Mapping[str, object] | None = None, trade_date: str | None = None) -> dict[str, object]`

- [ ] **Step 1: Write failing test**

Create `tests/test_operations_quality_report.py`:

```python
from pathlib import Path

from runtime.operations_ack import record_operations_ack
from runtime.operations_quality_report import build_operations_quality_report
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_operations_quality_report_writes_artifacts_and_registers_report(tmp_path: Path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    record_operations_ack(
        paths.system_state_path,
        {
            "trade_date": "20260703",
            "source": "system_smoke",
            "category": "operations_ack",
            "name": "e19_smoke",
            "severity": "NORMAL",
            "decision": "NO_ACTION",
            "message": "smoke",
            "resolution": "ok",
            "operator": "codex",
        },
    )

    result = build_operations_quality_report(paths, {"status": "READY", "checks": []}, trade_date="20260703")

    markdown_path = Path(result["markdown_path"])
    json_path = Path(result["json_path"])
    assert markdown_path.exists()
    assert json_path.exists()
    assert "运维质量趋势" in markdown_path.read_text(encoding="utf-8")
    reports = SystemRepository(paths.system_state_path).list_reports("operations")
    assert reports[0]["report_type"] == "operations_quality_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_quality_report.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement report writer**

Write Markdown and compact JSON to `reports/operations_quality/YYYYMMDD/`, register the Markdown report as:
- `report_type="operations_quality_review"`
- `strategy_id="operations"`
- `title="运维质量趋势 YYYYMMDD"`
- tags `["operations", "quality", "review"]`

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_quality_report.py -q`

Expected: `1 passed`.

### Task 2: API Route

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/api/local_server.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_operations_quality_report_api.py`

**Interfaces:**
- Produces: `POST /api/operations/quality-report`

- [ ] **Step 1: Write failing API test**

Create `tests/test_operations_quality_report_api.py`:

```python
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_operations_quality_report_api_generates_indexed_report(tmp_path) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.post("/api/operations/quality-report", json={"trade_date": "20260703"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "20260703"
    assert client.get("/api/reports").json()[0]["report_type"] == "operations_quality_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_quality_report_api.py -q`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement route**

Import and call `build_operations_quality_report` in `api/local_server.py`, passing `api_service.paths` and `api_service.readiness()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_quality_report_api.py -q`

Expected: `1 passed`.

### Task 3: Frontend Report Trigger

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/operations/qualityReportApi.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/pages/scheduler/SchedulerPage.tsx`

**Interfaces:**
- Consumes: `POST /api/operations/quality-report`
- Produces: a Scheduler page button that generates an indexed operations quality report and refreshes dashboard data.

- [ ] **Step 1: Implement typed API client**

Create `qualityReportApi.ts` using `postJson`.

- [ ] **Step 2: Add Scheduler page action**

Add a button in the “闭环复盘” panel: `生成运维复盘报告`. On success, show a message and call `data.refreshData()`.

- [ ] **Step 3: Run frontend tests**

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
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_operations_quality_report.py tests/test_operations_quality_report_api.py tests/test_operations_review.py tests/test_operations_review_api.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
./scripts/restart_services.sh
```

- [ ] **Step 2: Update planning state**

Mark E19.1 done and set next action to E20 after verification passes.

- [ ] **Step 3: Stage safely**

Stage only source, test, frontend, plan, and `.planning` files. Exclude generated reports and runtime data.

- [ ] **Step 4: Commit**

Run: `git commit -m "feat: add operations quality trend report"`

## Self-Review

- Spec coverage: E19 puts operations closure metrics into the report system and exposes a generation path.
- Placeholder scan: no TBD/TODO/implement-later placeholders.
- Type consistency: output keys `trade_date`, `markdown_path`, `json_path`, `review` are used consistently.
