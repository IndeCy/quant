# Manual Order Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest auditable manual rebalance workflow for shadow-live strategies without connecting to a broker.

**Architecture:** Reuse the existing `account_snapshots` and `account_positions` output as the source of rebalance intent. Add a persistent manual order layer in the local SQLite state database, expose it through the existing FastAPI local API, and display it in the strategy operations page. The workflow is `account snapshot -> draft manual orders -> user confirm -> fill/reject/cancel -> audit log`.

**Tech Stack:** Python 3, SQLite via `SystemRepository`, FastAPI local server, React + TypeScript frontend, Vitest, pytest.

## Global Constraints

- Do not connect to broker APIs.
- Do not modify M0 `ExecutionModel`.
- Do not change Alpha factors, strategy logic, or risk overlay parameters.
- Manual order workflow must be local-first and migratable with the existing `state/` directory.
- Every implementation task must start with a failing test.
- Keep Python modules focused and typed; key business logic comments should be in Chinese.

---

## File Structure

- Create `runtime/manual_order.py`: pure functions for converting account snapshot drift rows into manual order drafts and validating lifecycle transitions.
- Create `runtime/manual_order_repository.py`: SQLite repository mixin for order batches, order rows, and audit events.
- Modify `runtime/repository_schema.py`: add manual order tables with idempotent schema creation and indexes.
- Modify `runtime/repository.py`: mix in manual order repository.
- Modify `api/service.py`: expose manual order use cases to the local API service.
- Modify `api/local_server.py`: add REST endpoints under `/api/manual-orders`.
- Create `tests/test_manual_order_workflow.py`: repository and domain tests.
- Modify `tests/test_local_api_service.py`: API service and FastAPI route tests.
- Create `frontend/src/entities/manualOrder/*`: TypeScript model, API client, and status helpers.
- Create `frontend/src/pages/strategies/ManualOrderPanel.tsx`: strategy page panel for generated orders and fill/reject actions.
- Modify `frontend/src/pages/strategies/StrategiesPage.tsx`: load and render the manual order panel for selected strategy.

---

### Task 1: Manual Order Domain and Persistence

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/manual_order.py`
- Create: `/Users/admin/PycharmProjects/quant/runtime/manual_order_repository.py`
- Modify: `/Users/admin/PycharmProjects/quant/runtime/repository_schema.py`
- Modify: `/Users/admin/PycharmProjects/quant/runtime/repository.py`
- Test: `/Users/admin/PycharmProjects/quant/tests/test_manual_order_workflow.py`

**Interfaces:**
- Consumes: account snapshot dict from `SystemRepository.load_account_snapshot(strategy_id)`.
- Produces:
  - `build_order_draft_from_snapshot(snapshot: dict[str, Any], min_trade_amount: float = 100.0) -> dict[str, Any]`
  - `SystemRepository.create_manual_order_batch(snapshot: dict[str, Any], source: str = "account_snapshot") -> dict[str, Any]`
  - `SystemRepository.load_manual_order_batch(strategy_id: str, trade_date: str | None = None) -> dict[str, Any] | None`

- [ ] **Step 1: Write the failing domain and repository tests**

```python
from pathlib import Path

import pytest

from runtime.manual_order import build_order_draft_from_snapshot
from runtime.portfolio_account import build_account_snapshot
from runtime.repository import SystemRepository


def _snapshot() -> dict:
    return build_account_snapshot(
        strategy_id="quality_overlay",
        trade_date="20260702",
        total_value=1_000_000.0,
        cash=100_000.0,
        target_weights={"000001.SZ": 0.50, "000002.SZ": 0.30},
        actual_positions={
            "000001.SZ": {"market_value": 400_000.0, "quantity": 10_000, "last_close": 40.0},
            "000003.SZ": {"market_value": 100_000.0, "quantity": 2_000, "last_close": 50.0},
        },
    )


def test_build_order_draft_from_account_snapshot_filters_hold_rows() -> None:
    draft = build_order_draft_from_snapshot(_snapshot(), min_trade_amount=1_000.0)

    assert draft["strategy_id"] == "quality_overlay"
    assert draft["trade_date"] == "20260702"
    assert draft["status"] == "DRAFT"
    assert [item["symbol"] for item in draft["orders"]] == ["000001.SZ", "000002.SZ", "000003.SZ"]
    assert draft["orders"][0]["side"] == "BUY"
    assert draft["orders"][2]["side"] == "SELL"


def test_repository_persists_manual_order_batch_and_audit_log(tmp_path: Path) -> None:
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    created = repository.create_manual_order_batch(_snapshot())
    loaded = repository.load_manual_order_batch("quality_overlay", "20260702")

    assert loaded is not None
    assert loaded["batch_id"] == created["batch_id"]
    assert loaded["status"] == "DRAFT"
    assert len(loaded["orders"]) == 3
    assert loaded["audit_events"][0]["event_type"] == "CREATE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_manual_order_workflow.py -q`

Expected: FAIL because `runtime.manual_order` and repository methods are missing.

- [ ] **Step 3: Implement minimal domain and repository**

Add SQLite tables:
- `manual_order_batches(batch_id, strategy_id, trade_date, status, source, total_buy_amount, total_sell_amount, created_at, modified_at)`
- `manual_orders(order_id, batch_id, strategy_id, trade_date, symbol, side, status, target_weight, actual_weight, drift_weight, target_amount, actual_amount, trade_amount, suggested_quantity, suggested_price, filled_quantity, filled_price, reject_reason, created_at, modified_at)`
- `manual_order_audit_events(event_id, batch_id, order_id, event_type, message, created_at)`

Minimal statuses: `DRAFT`, `CONFIRMED`, `FILLED`, `REJECTED`, `CANCELLED`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_manual_order_workflow.py -q`

Expected: PASS.

---

### Task 2: Manual Order Lifecycle API

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/api/service.py`
- Modify: `/Users/admin/PycharmProjects/quant/api/local_server.py`
- Modify: `/Users/admin/PycharmProjects/quant/tests/test_local_api_service.py`
- Test: `/Users/admin/PycharmProjects/quant/tests/test_manual_order_workflow.py`

**Interfaces:**
- Consumes:
  - `SystemRepository.create_manual_order_batch(snapshot)`
  - `SystemRepository.confirm_manual_order_batch(batch_id)`
  - `SystemRepository.fill_manual_order(order_id, filled_quantity, filled_price)`
- Produces:
  - `POST /api/manual-orders/from-account/{strategy_id}`
  - `GET /api/manual-orders/{strategy_id}`
  - `POST /api/manual-orders/batches/{batch_id}/confirm`
  - `POST /api/manual-orders/orders/{order_id}/fill`
  - `POST /api/manual-orders/orders/{order_id}/reject`

- [ ] **Step 1: Write failing API tests**

```python
def test_local_api_service_generates_and_fills_manual_orders(tmp_path: Path) -> None:
    service = LocalApiService(_seed_runtime(tmp_path))
    snapshot = build_account_snapshot(
        strategy_id="quality_overlay",
        trade_date="20260702",
        total_value=1_000_000.0,
        cash=100_000.0,
        target_weights={"000001.SZ": 0.50},
        actual_positions={"000001.SZ": {"market_value": 400_000.0, "quantity": 10_000, "last_close": 40.0}},
    )
    service.system_repository.upsert_account_snapshot(snapshot)

    batch = service.create_manual_orders_from_account("quality_overlay")
    confirmed = service.confirm_manual_order_batch(batch["batch_id"])
    filled = service.fill_manual_order(batch["orders"][0]["order_id"], {"filled_quantity": 2500, "filled_price": 40.2})

    assert batch["status"] == "DRAFT"
    assert confirmed["status"] == "CONFIRMED"
    assert filled["status"] == "FILLED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_local_api_service.py::test_local_api_service_generates_and_fills_manual_orders -q`

Expected: FAIL because API methods are missing.

- [ ] **Step 3: Implement minimal service and route methods**

Service methods:
- `create_manual_orders_from_account(strategy_id: str) -> dict[str, Any]`
- `manual_order_batch(strategy_id: str) -> dict[str, Any] | None`
- `confirm_manual_order_batch(batch_id: str) -> dict[str, Any]`
- `fill_manual_order(order_id: str, payload: dict[str, Any]) -> dict[str, Any]`
- `reject_manual_order(order_id: str, payload: dict[str, Any]) -> dict[str, Any]`

Route errors:
- missing account snapshot -> `404`
- invalid lifecycle action -> `400`

- [ ] **Step 4: Run focused API tests**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_local_api_service.py::test_local_api_service_generates_and_fills_manual_orders -q`

Expected: PASS.

---

### Task 3: Strategy Page Manual Order Panel

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/manualOrder/model.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/manualOrder/api.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/manualOrder/status.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/entities/manualOrder/status.test.ts`
- Create: `/Users/admin/PycharmProjects/quant/frontend/src/pages/strategies/ManualOrderPanel.tsx`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/pages/strategies/StrategiesPage.tsx`
- Modify: `/Users/admin/PycharmProjects/quant/frontend/src/shared/styles/operations.css`

**Interfaces:**
- Consumes manual order API responses.
- Produces a local-only manual order panel with generate, confirm, fill, and reject actions.

- [ ] **Step 1: Write failing status helper test**

```typescript
import { expect, test } from "vitest";

import { manualOrderStatusTone, orderSideLabel } from "./status";

test("manualOrderStatusTone maps lifecycle statuses", () => {
  expect(manualOrderStatusTone("DRAFT")).toBe("warning");
  expect(manualOrderStatusTone("CONFIRMED")).toBe("success");
  expect(manualOrderStatusTone("REJECTED")).toBe("danger");
});

test("orderSideLabel translates buy and sell", () => {
  expect(orderSideLabel("BUY")).toBe("买入");
  expect(orderSideLabel("SELL")).toBe("卖出");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/manualOrder/status.test.ts`

Expected: FAIL because helper file is missing.

- [ ] **Step 3: Implement model, API, helper, and page panel**

Panel behavior:
- selected strategy has account snapshot but no manual order batch: show “生成手工调仓单”。
- batch is `DRAFT`: show confirm button.
- order is `CONFIRMED`: show fill and reject actions.
- filled/rejected orders remain visible with audit status.

- [ ] **Step 4: Run frontend tests and build**

Run:
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/manualOrder/status.test.ts`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre`

Expected: PASS.

---

### Task 4: Verification and Governance Update

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/.planning/STATE.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/TASKS.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/ROADMAP.md`

**Interfaces:**
- Consumes verified backend and frontend test output.
- Produces updated project state for checkpoint resume.

- [ ] **Step 1: Run full backend and frontend verification**

Run:
- `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre`
- `./scripts/restart_services.sh`

Expected: all pass and local services restart.

- [ ] **Step 2: Update governance files**

Set:
- `.planning/ROADMAP.md` E6.1 status to `done`
- `.planning/TASKS.md` E6-001 status to `done`
- `.planning/STATE.md` Last Completed append E6.1 and Next Action point to next milestone planning.

- [ ] **Step 3: Final smoke**

Run:
- `curl -s http://127.0.0.1:8765/api/health`
- `curl -I -s http://127.0.0.1:5173/ | head`

Expected: API status ok and frontend HTTP 200.

---

## Self-Review

- Spec coverage: covers manual order generation, confirmation, fill/reject, audit events, API, and frontend visibility.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: `batch_id`, `order_id`, `strategy_id`, `trade_date`, and status names are consistent across backend and frontend tasks.
