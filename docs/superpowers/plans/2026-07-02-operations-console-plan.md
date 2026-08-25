# Operations Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing local React console so it can operate the quant system through Data Catalog, Data Quality Gate, Factor Contracts, Strategy Lifecycle, and Account Snapshots.

**Architecture:** Keep the current Vite + React + entity/page structure. Add focused entity modules for data catalog, factor contract, and account snapshots; enhance existing data, factors, and strategies pages instead of adding new top-level routes.

**Tech Stack:** React 19, TypeScript strict mode, Vite, Vitest, existing FastAPI JSON endpoints.

## Global Constraints

- Do not add automatic trading or broker integration.
- Do not add new alpha factors or change strategy logic.
- Do not rewrite the frontend router/sidebar layout.
- Use existing `getJson` and `postJson` helpers.
- Keep page-specific fetches local to pages unless the data is shared across pages.
- Run frontend tests and `npm run build:pre` before declaring E5.1 complete.

---

## File Structure

- Create `frontend/src/entities/dataCatalog/model.ts`: Data Catalog and Quality Gate response types.
- Create `frontend/src/entities/dataCatalog/api.ts`: API calls for catalog refresh, source list/detail, quality gate.
- Create `frontend/src/entities/dataCatalog/status.ts`: status/tone and file-size helpers.
- Create `frontend/src/entities/dataCatalog/status.test.ts`: unit tests for data catalog helpers.
- Create `frontend/src/entities/factorContract/model.ts`: Factor Contract response type.
- Create `frontend/src/entities/factorContract/api.ts`: API calls for factor contract list/detail.
- Create `frontend/src/entities/factorContract/display.ts`: contract availability/as-of display helpers.
- Create `frontend/src/entities/factorContract/display.test.ts`: unit tests for contract helpers.
- Create `frontend/src/entities/account/model.ts`: account snapshot and position types.
- Create `frontend/src/entities/account/api.ts`: API call for account snapshot.
- Create `frontend/src/entities/account/drift.ts`: account position sorting and drift summary helpers.
- Create `frontend/src/entities/account/drift.test.ts`: unit tests for drift helpers.
- Modify `frontend/src/entities/strategy/api.ts`: add lifecycle transition API.
- Modify `frontend/src/entities/strategy/model.ts`: add lifecycle payload type.
- Create `frontend/src/entities/strategy/lifecycle.ts`: allowed transition labels and status tone helpers.
- Create `frontend/src/entities/strategy/lifecycle.test.ts`: unit tests for lifecycle helpers.
- Modify `frontend/src/pages/data/DataHealthPage.tsx`: add catalog and gate panels.
- Modify `frontend/src/pages/factors/FactorsPage.tsx`: add factor contract panel.
- Modify `frontend/src/pages/strategies/StrategiesPage.tsx`: add lifecycle actions and account snapshot panel.
- Modify `frontend/src/shared/styles/features.css`: add small layout classes used by new panels.

---

## Task 1: Data Catalog and Quality Gate Panels

**Files:**
- Create: `frontend/src/entities/dataCatalog/model.ts`
- Create: `frontend/src/entities/dataCatalog/api.ts`
- Create: `frontend/src/entities/dataCatalog/status.ts`
- Create: `frontend/src/entities/dataCatalog/status.test.ts`
- Modify: `frontend/src/pages/data/DataHealthPage.tsx`

**Interfaces:**
- Consumes: `getJson<T>()`, `postJson<T>()` from `frontend/src/shared/api/client.ts`
- Produces:
  - `listDataSources(): Promise<DataSource[]>`
  - `getDataSource(datasetId: string): Promise<DataSourceDetail>`
  - `refreshDataCatalog(): Promise<DataCatalogRefreshResult>`
  - `runDataQualityGate(minTradeDate?: string): Promise<DataQualityGateResult>`
  - `catalogTone(status: string): "success" | "warning" | "danger" | "neutral"`
  - `formatBytes(size: number): string`

- [ ] **Step 1: Write the failing helper tests**

```ts
import { catalogTone, formatBytes, qualityGateSummary } from "./status";

test("catalogTone maps source status to visual tone", () => {
  expect(catalogTone("OK")).toBe("success");
  expect(catalogTone("ERROR")).toBe("danger");
  expect(catalogTone("UNKNOWN")).toBe("neutral");
});

test("formatBytes renders compact file sizes", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(2048)).toBe("2.0 KB");
  expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
});

test("qualityGateSummary highlights failures", () => {
  expect(qualityGateSummary({ status: "PASS", check_count: 5, failed_count: 0, checks: [] }).tone).toBe("success");
  expect(qualityGateSummary({ status: "FAIL", check_count: 5, failed_count: 2, checks: [] }).label).toBe("2/5 failed");
});
```

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/dataCatalog/status.test.ts`

Expected: FAIL because module does not exist.

- [ ] **Step 2: Implement data catalog entity files**

Create model, API, and status helpers using the signatures above. Types must include `dataset_id`, `file_path`, `database_type`, `size_bytes`, `status`, `latest_date`, and table-level metadata.

- [ ] **Step 3: Verify helper tests pass**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/dataCatalog/status.test.ts`

Expected: PASS.

- [ ] **Step 4: Add Data Catalog UI to data page**

Enhance `DataHealthPage.tsx` with:

- Existing health cards remain at top.
- Catalog panel lists sources.
- Selected source detail lists tables.
- Buttons for refresh and quality gate.
- Local errors appear inside data page panels.

- [ ] **Step 5: Run page-related tests**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/dataCatalog/status.test.ts src/entities/dataHealth/status.test.ts`

Expected: PASS.

---

## Task 2: Factor Contract Visibility

**Files:**
- Create: `frontend/src/entities/factorContract/model.ts`
- Create: `frontend/src/entities/factorContract/api.ts`
- Create: `frontend/src/entities/factorContract/display.ts`
- Create: `frontend/src/entities/factorContract/display.test.ts`
- Modify: `frontend/src/pages/factors/FactorsPage.tsx`

**Interfaces:**
- Produces:
  - `listFactorContracts(): Promise<FactorContract[]>`
  - `getFactorContract(factorId: string): Promise<FactorContract>`
  - `contractStatusLabel(contract?: FactorContract | null): string`
  - `asOfLabel(contract?: FactorContract | null): string`

- [ ] **Step 1: Write failing display tests**

```ts
import { asOfLabel, contractStatusLabel } from "./display";

test("contractStatusLabel distinguishes contract availability", () => {
  expect(contractStatusLabel(null)).toBe("无契约");
  expect(contractStatusLabel({ factor_id: "roa", status: "active" } as never)).toBe("有契约");
});

test("asOfLabel renders financial announcement field", () => {
  expect(asOfLabel({ as_of_policy: "financial_announcement", as_of_field: "f_ann_date" } as never)).toBe(
    "financial_announcement / f_ann_date"
  );
});
```

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/factorContract/display.test.ts`

Expected: FAIL because module does not exist.

- [ ] **Step 2: Implement factor contract entity files**

Create typed API and display helpers. Keep contract editing out of scope.

- [ ] **Step 3: Verify display tests pass**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/factorContract/display.test.ts`

Expected: PASS.

- [ ] **Step 4: Enhance factors page**

Load contracts locally on page mount. In the factor detail panel, show:

- contract status
- as-of policy/field
- frequency/value_type
- input datasets
- input fields
- output fields
- validation JSON

If no contract exists, show “无契约，只能作为草案或研究素材”.

- [ ] **Step 5: Run factor tests**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/factorContract/display.test.ts src/entities/factor/usage.test.ts`

Expected: PASS.

---

## Task 3: Strategy Lifecycle and Account Snapshot

**Files:**
- Create: `frontend/src/entities/account/model.ts`
- Create: `frontend/src/entities/account/api.ts`
- Create: `frontend/src/entities/account/drift.ts`
- Create: `frontend/src/entities/account/drift.test.ts`
- Modify: `frontend/src/entities/strategy/api.ts`
- Modify: `frontend/src/entities/strategy/model.ts`
- Create: `frontend/src/entities/strategy/lifecycle.ts`
- Create: `frontend/src/entities/strategy/lifecycle.test.ts`
- Modify: `frontend/src/pages/strategies/StrategiesPage.tsx`

**Interfaces:**
- Produces:
  - `getAccountSnapshot(strategyId: string): Promise<AccountSnapshot>`
  - `transitionStrategyInstance(strategyId: string, payload: StrategyTransitionPayload): Promise<StrategyInstance>`
  - `sortAccountPositions(positions: AccountPosition[]): AccountPosition[]`
  - `maxDriftLabel(snapshot?: AccountSnapshot | null): string`
  - `transitionCandidates(status: string): Array<{ target_status: string; label: string }>`

- [ ] **Step 1: Write failing account and lifecycle tests**

```ts
import { maxDriftLabel, sortAccountPositions } from "../account/drift";
import { transitionCandidates } from "./lifecycle";

test("sortAccountPositions prioritizes trade actions and drift", () => {
  const result = sortAccountPositions([
    { symbol: "B", action: "HOLD", drift_weight: 0.01 } as never,
    { symbol: "A", action: "SELL", drift_weight: -0.03 } as never,
    { symbol: "C", action: "BUY", drift_weight: 0.05 } as never
  ]);
  expect(result.map((item) => item.symbol)).toEqual(["C", "A", "B"]);
});

test("maxDriftLabel formats empty and populated snapshots", () => {
  expect(maxDriftLabel(null)).toBe("-");
  expect(maxDriftLabel({ max_abs_drift: 0.1234 } as never)).toBe("12.34%");
});

test("transitionCandidates follows lifecycle sequence", () => {
  expect(transitionCandidates("research").map((item) => item.target_status)).toEqual(["paper", "paused", "retired"]);
});
```

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/account/drift.test.ts src/entities/strategy/lifecycle.test.ts`

Expected: FAIL because modules do not exist.

- [ ] **Step 2: Implement account and lifecycle entity files**

Add account types and API. Add strategy transition payload and API function to existing strategy entity.

- [ ] **Step 3: Verify entity tests pass**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/account/drift.test.ts src/entities/strategy/lifecycle.test.ts`

Expected: PASS.

- [ ] **Step 4: Enhance strategies page**

Add to `StrategiesPage.tsx`:

- Strategy instance lifecycle controls.
- Transition buttons based on selected instance status.
- Error text for failed transition.
- Account snapshot panel for selected instance.
- Empty account state if `/api/accounts/{strategy_id}` returns 404.

Do not auto-enable strategies through UI unless user explicitly chooses lifecycle transition with `enable`.

- [ ] **Step 5: Run strategy-related tests**

Run: `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test -- src/entities/account/drift.test.ts src/entities/strategy/lifecycle.test.ts src/entities/strategy/instanceFactory.test.ts`

Expected: PASS.

---

## Task 4: Build Verification and Service Restart

**Files:**
- Modify: `.planning/STATE.md`
- Modify: `.planning/TASKS.md`
- Modify: `.planning/ROADMAP.md`

**Interfaces:**
- Consumes: successful Tasks 1-3.
- Produces: E5.1 marked done and E6.1 remains blocked until manual order workflow is deliberately started.

- [ ] **Step 1: Run frontend tests**

Run:

```bash
cd frontend
PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test
```

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend
PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre
```

Expected: PASS.

- [ ] **Step 3: Restart local services after build**

Run:

```bash
./scripts/restart_services.sh
```

Expected: API and frontend restart without stale build artifacts.

- [ ] **Step 4: Run backend regression tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Update planning state**

Update:

- `.planning/TASKS.md`: E5-001 done.
- `.planning/ROADMAP.md`: Phase E5.1 done.
- `.planning/STATE.md`: latest completed includes E5.1; next action remains E6.1 blocked unless user explicitly starts manual order workflow.

---

## Self-Review

- Spec coverage: Data Catalog, Quality Gate, Factor Contract, Strategy Lifecycle, Account Snapshot, tests, and build gate are each covered by one task.
- Placeholder scan: no placeholder markers are present.
- Type consistency: API function names and helper names are defined before page tasks reference them.
