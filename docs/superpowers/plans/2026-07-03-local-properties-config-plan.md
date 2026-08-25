# Local Properties Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scattered runtime environment dependencies with a local `.env.properties` KV configuration file that is never committed.

**Architecture:** Add `runtime.config` as the only code path that reads private runtime configuration. Runtime modules read `TUSHARE_TOKEN`, Bark URL, `QUANT_HOME`, and broker switches through this helper; `.env.properties` is ignored by Git and `.env.properties.example` documents required keys.

**Tech Stack:** Python 3, UTF-8 Java-properties-style `key=value` parsing, pytest.

## Global Constraints

- `.env.properties` stores local secrets and must not be committed.
- Keep environment variables only as compatibility fallback inside `runtime.config`.
- Do not change strategy logic, factor logic, scheduler timing, or Tushare data behavior.
- Do not print token values in logs, tests, or API responses.

---

### Task 1: Config Reader

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/config.py`
- Create: `/Users/admin/PycharmProjects/quant/tests/test_runtime_config.py`
- Modify: `/Users/admin/PycharmProjects/quant/.gitignore`
- Create: `/Users/admin/PycharmProjects/quant/.env.properties.example`

**Interfaces:**
- Produces: `load_properties_file(path: Path | None = None) -> dict[str, str]`
- Produces: `get_config_value(key: str, default: str = "", *, config_path: Path | None = None, environ: Mapping[str, str] | None = None, prefer_environ: bool = False) -> str`
- Produces: `get_config_flag(key: str, default: bool = False, *, config_path: Path | None = None) -> bool`

- [x] **Step 1: Write failing tests**

Covered parsing comments, empty values, file priority, and environment fallback in `tests/test_runtime_config.py`.

- [x] **Step 2: Run test to verify it fails**

Ran `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_runtime_config.py -q`; expected failure was `ModuleNotFoundError`.

- [x] **Step 3: Implement config reader and ignore real config**

Implemented `runtime/config.py`, added `.env.properties` to `.gitignore`, and added `.env.properties.example`.

- [x] **Step 4: Run test to verify it passes**

Ran `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_runtime_config.py -q`; result `2 passed`.

### Task 2: Runtime Integration

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/runtime/paths.py`
- Modify: `/Users/admin/PycharmProjects/quant/runtime/notification_config.py`
- Modify: `/Users/admin/PycharmProjects/quant/runtime/mainline_tushare_backfill.py`
- Modify: `/Users/admin/PycharmProjects/quant/api/service.py`
- Modify: `/Users/admin/PycharmProjects/quant/runtime/environment_audit.py`
- Modify: `/Users/admin/PycharmProjects/quant/tests/test_environment_audit.py`

**Interfaces:**
- Consumes: `get_config_value(...)`, `get_config_flag(...)`
- Produces: readiness and environment audit based on `.env.properties`.

- [x] **Step 1: Write failing audit test**

Added `test_environment_audit_accepts_properties_file_as_runtime_config`, which requires Tushare and Bark checks to pass from `.env.properties`.

- [x] **Step 2: Run test to verify it fails**

Ran `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_environment_audit.py::test_environment_audit_accepts_properties_file_as_runtime_config -q`; expected failure was unsupported `config_path`.

- [x] **Step 3: Integrate config reader**

Updated runtime path resolution, Bark resolution, Tushare backfill, API readiness, broker switch, and environment audit to use `runtime.config`.

- [x] **Step 4: Run focused and full tests**

Ran focused tests and full backend suite; final backend result was `459 passed`.

### Task 3: Real Local Config and Verification

**Files:**
- Create local-only: `/Users/admin/PycharmProjects/quant/.env.properties`

- [x] **Step 1: Create real ignored config**

Created `.env.properties` from existing local launchd values without printing secret values.

- [x] **Step 2: Verify Git ignore**

Ran `git check-ignore -v .env.properties`; result matched `.gitignore`.

- [x] **Step 3: Restart services**

Ran `./scripts/restart_services.sh`.

- [x] **Step 4: Verify runtime status**

Ran `/api/readiness` and `/api/environment/audit`; final status was `READY` and `PASS`, with `secret_values_exposed=false`.

## Self-Review

- Spec coverage: local `.env.properties` exists, is ignored, and key runtime dependencies read through a single config module.
- Placeholder scan: no TBD/TODO/implement-later placeholders.
- Type consistency: all integrations use `get_config_value` or `get_config_flag`.
