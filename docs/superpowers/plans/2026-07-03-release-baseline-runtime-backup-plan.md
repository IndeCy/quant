# Release Baseline and Runtime Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible release baseline package that backs up local runtime data and records the code/worktree state needed for migration to a Mac mini.

**Architecture:** Extend the existing backup concept from a read-only manifest into an executable local module. The module creates a tar.gz archive of `QUANT_HOME` runtime directories, writes a JSON release manifest next to it, and generates a short restore guide. Keep this as CLI/module work only; do not add API endpoints to the already large local API service.

**Tech Stack:** Python 3 standard library (`tarfile`, `json`, `subprocess`, `pathlib`), existing `RuntimePaths`, pytest.

## Global Constraints

- Do not include broker credentials or secrets in generated manifests.
- Do not modify strategy, factor, scheduler, or execution logic.
- Do not commit or clean unrelated dirty worktree changes.
- Runtime data is valuable and must be backed up before release/migration.
- Keep new files under 500 lines.
- Every implementation task must start with a failing test.

---

## File Structure

- Create `/Users/admin/PycharmProjects/quant/runtime/release_baseline.py`: builds archive, release manifest, and restore guide.
- Create `/Users/admin/PycharmProjects/quant/scripts/create_release_baseline.py`: CLI wrapper.
- Create `/Users/admin/PycharmProjects/quant/tests/test_release_baseline.py`: module behavior tests.
- Modify `/Users/admin/PycharmProjects/quant/runtime/backup.py`: optional helper reuse only if needed.
- Modify `.planning` files after verification.

---

### Task 1: Release Baseline Module

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/runtime/release_baseline.py`
- Test: `/Users/admin/PycharmProjects/quant/tests/test_release_baseline.py`

**Interfaces:**
- Consumes: `RuntimePaths`, project root path, optional output directory.
- Produces:
  - `create_release_baseline(paths: RuntimePaths, output_dir: Path | None = None, label: str = "release") -> dict[str, Any]`
  - archive path ending in `.tar.gz`
  - manifest path ending in `.json`
  - restore guide path ending in `.md`

- [ ] **Step 1: Write failing test**

```python
from pathlib import Path
import tarfile

from runtime.paths import RuntimePaths
from runtime.release_baseline import create_release_baseline


def test_create_release_baseline_archives_runtime_and_manifest(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    paths.system_state_path.write_text("state", encoding="utf-8")
    paths.logs_dir.joinpath("api.log").write_text("ok", encoding="utf-8")

    result = create_release_baseline(paths=paths, output_dir=tmp_path / "backups", label="smoke")

    assert Path(result["archive_path"]).exists()
    assert Path(result["manifest_path"]).exists()
    assert Path(result["restore_guide_path"]).exists()
    assert result["included_dirs"] == ["data", "state", "runs", "reports", "config", "logs"]
    with tarfile.open(result["archive_path"], "r:gz") as archive:
        names = archive.getnames()
    assert "runtime/state/system_state.sqlite" in names
    assert "runtime/logs/api.log" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_release_baseline.py -q`

Expected: FAIL because `runtime.release_baseline` does not exist.

- [ ] **Step 3: Implement minimal module**

Implementation details:
- Archive includes only `data`, `state`, `runs`, `reports`, `config`, `logs`.
- Manifest includes:
  - `label`
  - `generated_at`
  - `runtime_root`
  - `archive_path`
  - `included_dirs`
  - `git_branch`
  - `git_head`
  - `git_dirty`
  - `restore_steps`
- Do not serialize environment variables or token values.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_release_baseline.py -q`

Expected: PASS.

---

### Task 2: CLI Entry

**Files:**
- Create: `/Users/admin/PycharmProjects/quant/scripts/create_release_baseline.py`
- Modify: `/Users/admin/PycharmProjects/quant/tests/test_release_baseline.py`

**Interfaces:**
- CLI arguments:
  - `--output-dir`
  - `--label`
- Produces JSON on stdout.

- [ ] **Step 1: Write failing CLI smoke test**

```python
def test_create_release_baseline_cli_outputs_manifest(tmp_path: Path) -> None:
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_release_baseline.py -q`

Expected: FAIL because script is missing.

- [ ] **Step 3: Implement CLI**

The script should:
- insert project root into `sys.path`
- parse args
- call `create_release_baseline`
- print JSON with `ensure_ascii=False`

- [ ] **Step 4: Run focused tests**

Run: `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest tests/test_release_baseline.py -q`

Expected: PASS.

---

### Task 3: Real Local Backup Smoke

**Files:**
- No code changes expected after Task 2.

**Verification:**
- Run:
  - `/Users/admin/recommend_analysis/.venv/bin/python3 scripts/create_release_baseline.py --output-dir runtime_backups --label e8_1_smoke`
- Expected:
  - a `.tar.gz`
  - a `.json`
  - a `.md`
  under `runtime_backups/`

---

### Task 4: Full Verification and Governance

**Files:**
- Modify: `/Users/admin/PycharmProjects/quant/.planning/STATE.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/TASKS.md`
- Modify: `/Users/admin/PycharmProjects/quant/.planning/ROADMAP.md`

**Verification:**
- `/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm test`
- `cd frontend && PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build:pre`
- `./scripts/restart_services.sh`

---

## Self-Review

- Spec coverage: runtime backup, release manifest, restore guide, CLI smoke, governance update.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: `archive_path`, `manifest_path`, `restore_guide_path`, and `included_dirs` are consistent across module and tests.
