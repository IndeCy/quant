# Live Readiness Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the production readiness audit so small-capital live preparation cannot proceed unless data, strategy runtime, manual orders, notification, backup, and broker-permission boundaries are explicitly checked.

**Architecture:** Reuse the existing `runtime.readiness.build_readiness_report()` and `/api/readiness` endpoint. Add optional checks for backup coverage, Bark notification configuration, manual order workflow availability, and broker auto-trading disablement. The frontend already renders readiness checks generically, so only label coverage needs to be extended.

**Tech Stack:** Python 3, SQLite state repository, FastAPI local API, React + TypeScript, pytest, Vitest.

## Global Constraints

- Do not connect to broker APIs.
- Do not add automatic order submission.
- Do not modify strategy logic, factors, or M0 execution semantics.
- Audit must be evidence-based and visible in the existing readiness panel.
- Every implementation task must start with a failing test.
- Keep all new files under 500 lines.

---

## File Structure

- Modify `/Users/admin/PycharmProjects/quant/runtime/readiness.py`: add optional live-readiness checks while preserving current API callers.
- Modify `/Users/admin/PycharmProjects/quant/api/service.py`: pass backup, notification, manual-order, and broker-boundary evidence into readiness.
- Modify `/Users/admin/PycharmProjects/quant/frontend/src/pages/dashboard/components/ReadinessPanel.tsx`: add Chinese labels for new checks.
- Modify `/Users/admin/PycharmProjects/quant/tests/test_runtime_readiness.py`: cover full live readiness PASS and FAIL conditions.
- Modify `/Users/admin/PycharmProjects/quant/tests/test_local_api_service.py`: verify `/api/readiness` includes new audit items.
- Modify `/Users/admin/PycharmProjects/quant/frontend/src/entities/readiness/status.test.ts`: verify readiness status helpers still map correctly.

---

### Task 1: Extend Readiness Core Checks

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/runtime/readiness.py`
- Modify: `/Users/admin/PycharmProjects/quant/tests/test_runtime_readiness.py`

**Interfaces:**
- Consumes:
  - `backup_manifest: dict[str, Any] | None`
  - `notification_configured: bool`
  - `manual_order_ready: bool`
  - `broker_auto_trading_enabled: bool`
- Produces:
  - Additional readiness checks:
    - `backup_manifest`
    - `notification_channel`
    - `manual_order_workflow`
    - `broker_permission_boundary`

- [ ] **Step 1: Write failing tests**

```python
def test_build_readiness_report_includes_live_trading_preflight_checks() -> None:
    report = build_readiness_report(
        token_present=True,
        data_health={
            "live_market_increment": {"exists": True, "latest_daily_date": "20260626", "latest_adj_factor_date": "20260626"},
            "benchmark_increment": {"exists": True, "latest_fund_date": "20260626", "latest_fund_adj_date": "20260626"},
            "monitoring": {"exists": True},
            "system_state": {"exists": True},
        },
        scheduler_status={"enabled": True},
        service_status={"services": [{"name": "api", "running": True}, {"name": "frontend", "running": True}, {"name": "scheduler", "running": True}]},
        backup_manifest={"items": [{"name": name, "exists": True} for name in ["data", "state", "runs", "reports", "config", "logs"]]},
        notification_configured=True,
        manual_order_ready=True,
        broker_auto_trading_enabled=False,
    )

    names = [item["name"] for item in report["checks"]]
    assert report["status"] == "READY"
    assert names[-4:] == ["backup_manifest", "notification_channel", "manual_order_workflow", "broker_permission_boundary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_runtime_readiness.py -q`

Expected: FAIL because `build_readiness_report()` does not accept new arguments.

- [ ] **Step 3: Implement minimal optional checks**

Implementation rules:
- Existing callers without new arguments must still work.
- `backup_manifest` passes only when `data/state/runs/reports/config/logs` all exist.
- `notification_channel` passes when Bark URL resolution found a configured endpoint.
- `manual_order_workflow` passes when the local state DB has the manual-order workflow initialized.
- `broker_permission_boundary` passes when automatic broker trading is disabled.

- [ ] **Step 4: Run focused tests**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_runtime_readiness.py -q`

Expected: PASS.

---

### Task 2: Wire Local API Evidence

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/api/service.py`
- Modify: `/Users/admin/PycharmProjects/quant/tests/test_local_api_service.py`

**Interfaces:**
- Consumes:
  - `build_backup_manifest(self.paths)`
  - `resolve_bark_url()`
  - `QUANT_ENABLE_BROKER_TRADING`
  - system-state SQLite manual order tables.
- Produces:
  - `/api/readiness` containing new checks.

- [ ] **Step 1: Write failing service test**

```python
def test_local_api_service_readiness_includes_live_preflight_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setenv("BARK_PUSH_URL", "https://api.day.app/key")
    monkeypatch.delenv("QUANT_ENABLE_BROKER_TRADING", raising=False)
    service = LocalApiService(_seed_runtime(tmp_path))

    report = service.readiness()

    names = [item["name"] for item in report["checks"]]
    assert "backup_manifest" in names
    assert "notification_channel" in names
    assert "manual_order_workflow" in names
    assert "broker_permission_boundary" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_local_api_service.py::test_local_api_service_readiness_includes_live_preflight_items -q`

Expected: FAIL because service readiness does not pass the new evidence.

- [ ] **Step 3: Implement service wiring**

Add small helpers in `api/service.py` only if needed:
- `_manual_order_tables_ready(path: Path) -> bool`
- broker flag reads `QUANT_ENABLE_BROKER_TRADING` and treats only `"1"`, `"true"`, `"yes"` as enabled.

- [ ] **Step 4: Run focused tests**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_local_api_service.py::test_local_api_service_readiness_includes_live_preflight_items -q`

Expected: PASS.

---

### Task 3: Frontend Readiness Labels

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/pages/dashboard/components/ReadinessPanel.tsx`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/entities/readiness/status.test.ts`

**Interfaces:**
- Consumes readiness check names from backend.
- Produces readable dashboard labels for new audit checks.

- [ ] **Step 1: Add label coverage expectation**

The readiness panel should have labels for:
- `backup_manifest`
- `notification_channel`
- `manual_order_workflow`
- `broker_permission_boundary`

- [ ] **Step 2: Implement labels**

Add Chinese labels:
- `backup_manifest`: `备份清单`
- `notification_channel`: `Bark 通知`
- `manual_order_workflow`: `手工调仓闭环`
- `broker_permission_boundary`: `券商权限边界`

- [ ] **Step 3: Run frontend tests and build**

Run:
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre`

Expected: PASS.

---

### Task 4: Full Verification and Governance

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/.planning/STATE.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/TASKS.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/ROADMAP.md`

**Interfaces:**
- Consumes full test and service smoke evidence.
- Produces updated project checkpoint.

- [ ] **Step 1: Run verification**

Run:
- `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre`
- `./scripts/restart_services.sh`

- [ ] **Step 2: Smoke check**

Run:
- `curl -s http://127.0.0.1:8765/api/readiness`
- `curl -I -s http://127.0.0.1:5173/ | head`

- [ ] **Step 3: Update governance**

Set E7.1 to `done` only if readiness includes all new audit checks and verification passes.

---

## Self-Review

- Spec coverage: covers data, strategy runtime via existing checks, manual orders, notification, backup, and broker permission boundary.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: readiness check names are consistent across backend and frontend.
