# Runtime Environment Consistency Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect drift between terminal/API/scheduler launchd environments for critical quant runtime variables.

**Architecture:** Add a read-only `runtime.environment_audit` module that inspects the current process environment and launchd plists without exposing secret values. Expose the audit through FastAPI and surface it on the Settings page so readiness failures like missing `TUSHARE_TOKEN` can be traced to the exact process boundary.

**Tech Stack:** Python 3, macOS launchd plist parsing, FastAPI, React + TypeScript + Vite.

## Global Constraints

- 不修改 launchd plist，不写环境变量，不重启服务。
- 不运行策略、不运行 Tushare、不发送 Bark。
- 不在 API 或前端暴露 token 原文，只返回 `present`、`fingerprint`、`source` 和状态。
- `api/service.py` 已接近 500 行，本阶段不修改它。
- 新行为必须先写失败测试，再实现。

---

### Task 1: Runtime Environment Audit Module

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/environment_audit.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_environment_audit.py`

**Interfaces:**
- Produces: `build_environment_audit(env: Mapping[str, str] | None = None, launch_agents_dir: Path | None = None) -> dict[str, object]`

- [x] **Step 1: Write failing tests**

Create `tests/test_environment_audit.py`:

```python
from pathlib import Path
import plistlib

from runtime.environment_audit import build_environment_audit


def _write_plist(path: Path, env: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"Label": path.stem, "EnvironmentVariables": env}
    with path.open("wb") as file:
        plistlib.dump(payload, file)


def test_environment_audit_detects_api_missing_tushare_token(tmp_path: Path) -> None:
    launch_dir = tmp_path / "LaunchAgents"
    _write_plist(launch_dir / "com.quant.api.plist", {"QUANT_HOME": "/tmp/quant"})
    _write_plist(launch_dir / "com.quant.scheduler.plist", {"QUANT_HOME": "/tmp/quant", "TUSHARE_TOKEN": "secret-token"})

    audit = build_environment_audit(env={"QUANT_HOME": "/tmp/quant"}, launch_agents_dir=launch_dir)

    assert audit["status"] == "FAIL"
    assert audit["secret_values_exposed"] is False
    names = {item["name"]: item for item in audit["checks"]}
    assert names["TUSHARE_TOKEN"]["status"] == "FAIL"
    assert "api_launchd" in names["TUSHARE_TOKEN"]["missing_in"]


def test_environment_audit_passes_when_required_sources_match(tmp_path: Path) -> None:
    launch_dir = tmp_path / "LaunchAgents"
    env = {"QUANT_HOME": "/tmp/quant", "TUSHARE_TOKEN": "secret-token", "BARK_PUSH_URL": "https://api.day.app/key"}
    _write_plist(launch_dir / "com.quant.api.plist", env)
    _write_plist(launch_dir / "com.quant.scheduler.plist", env)

    audit = build_environment_audit(env=env, launch_agents_dir=launch_dir)

    assert audit["status"] == "PASS"
    assert all(item["status"] == "PASS" for item in audit["checks"])
```

- [x] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_environment_audit.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement audit**

Inspect current env and launchd plists for:
- `TUSHARE_TOKEN`: required in `process`, `api_launchd`, `scheduler_launchd`;
- `QUANT_HOME`: required in `process`, `api_launchd`, `scheduler_launchd`, `frontend_launchd`;
- Bark: at least one of `BARK_PUSH_URL`, `BARK_URL`, `QUANT_BARK_URL` in `process` or `scheduler_launchd`.

Return only presence and short SHA256 fingerprints.

- [x] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_environment_audit.py -q`

Expected: `2 passed`.

### Task 2: Local API Route

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/api/local_server.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_environment_audit_api.py`

**Interfaces:**
- Produces: `GET /api/environment/audit`

- [x] **Step 1: Write failing API test**

Create `tests/test_environment_audit_api.py`:

```python
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from runtime.paths import RuntimePaths


def test_environment_audit_api_does_not_expose_secret_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token")
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.get("/api/environment/audit")

    assert response.status_code == 200
    payload = response.json()
    assert "secret-token" not in str(payload)
    assert "checks" in payload
```

- [x] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_environment_audit_api.py -q`

Expected: FAIL with HTTP 404.

- [x] **Step 3: Implement route**

Import `build_environment_audit` in `api/local_server.py` and expose `GET /api/environment/audit`.

- [x] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_environment_audit_api.py -q`

Expected: `1 passed`.

### Task 3: Frontend Settings Panel

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/environment/model.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/environment/api.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/environment/status.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/environment/status.test.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/types.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/app/loadDashboardData.ts`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/pages/settings/SettingsPage.tsx`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/shared/styles/environment.css`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/environment/audit`
- Produces: Settings page environment consistency panel.

- [x] **Step 1: Write failing frontend test**

Create `frontend/src/entities/environment/status.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { environmentAuditTitle, environmentAuditTone } from "./status";

describe("environment audit status helpers", () => {
  it("maps audit status to dashboard labels", () => {
    expect(environmentAuditTitle("PASS")).toBe("环境一致");
    expect(environmentAuditTitle("FAIL")).toBe("环境漂移");
    expect(environmentAuditTone("PASS")).toBe("success");
    expect(environmentAuditTone("FAIL")).toBe("danger");
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- environment/status`

Expected: FAIL because `status` does not exist.

- [x] **Step 3: Implement frontend integration**

Load environment audit with dashboard data and render a Settings page panel showing status, missing sources, and recommendations.

- [x] **Step 4: Run frontend tests**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- environment`

Expected: environment tests pass.

### Task 4: Verification and Commit

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/.planning/STATE.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/ROADMAP.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/TASKS.md`

- [x] **Step 1: Run verification**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_environment_audit.py tests/test_environment_audit_api.py -q
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
./scripts/restart_services.sh
```

- [x] **Step 2: Update planning state**

Mark E20.1 done and set next action to E21 after verification passes.

- [x] **Step 3: Stage safely**

Stage only source, test, frontend, plan, and `.planning` files. Exclude generated reports and runtime data.

- [x] **Step 4: Commit**

Run: `git commit -m "feat: add runtime environment consistency audit"`

## Self-Review

- Spec coverage: E20 detects process/launchd environment drift and hides secret values.
- Placeholder scan: no TBD/TODO/implement-later placeholders.
- Type consistency: backend and frontend both use `status`, `checks`, `missing_in`, `recommendation`.
