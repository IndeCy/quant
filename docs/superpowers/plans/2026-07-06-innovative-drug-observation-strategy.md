# Innovative Drug Observation Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `innovative_drug_globalization_observer_v0` as a daily runnable research-observation strategy with target observation holdings, monitoring history, reports, and frontend visibility.

**Architecture:** Add a reusable `opportunity_observer` strategy template that consumes existing opportunity theme monitor data and writes observation-only outputs. The runner records NAV-like observation history to the existing monitoring repository and state/holdings to the existing strategy instance state tables, while lifecycle guards prevent it from becoming a formal rebalance or trading source.

**Tech Stack:** Python 3, SQLite system state, monitoring SQLite, Pandas, existing Tushare/qfq local cache, FastAPI local API, React/Vite frontend, pytest, Vitest.

## Global Constraints

- Do not modify M0 ExecutionModel.
- Do not add Alpha factors.
- Do not change Quality Alpha V1 or mainline chain strategy logic.
- Do not write observation holdings into formal `rebalance_plan.csv`.
- Do not write observation holdings into real portfolio accounts.
- Do not trigger buy/sell reminders from this observation strategy.
- `research_observation` means daily runnable but non-trading.
- First version only uses existing opportunity monitor metrics and cached qfq market data.
- Python changes must have focused tests.
- Frontend changes must run `npm test -- --run` and preferably `npm run build`.

---

## File Structure

- Modify `runtime/strategy_lifecycle.py`: add `research_observation` as a runnable-but-non-trading lifecycle status and valid transitions.
- Modify `runtime/strategy_templates.py`: expose `opportunity_observer` template.
- Modify `runtime/strategy_catalog.py`: register strategy definition for `innovative_drug_globalization_observer_v0`.
- Modify `runtime/strategy_instance_catalog.py`: register enabled observation instance.
- Create `strategies/opportunity_observer_runner.py`: reusable observer runner for any opportunity theme.
- Modify `runtime/strategy_batch_runner.py`: dispatch `template_id == "opportunity_observer"`.
- Modify `runtime/daily_pipeline.py`: keep observation strategy in normal batch output but make operation summary say observation-only.
- Modify `frontend/src/entities/strategy/lifecycle.ts`: display lifecycle actions and tones for `research_observation`.
- Modify `frontend/src/pages/strategies/StrategiesPage.tsx`: show observation-only warning and suppress account/manual-order emphasis for observation strategies.
- Add/modify tests under `tests/` and `frontend/src/entities/strategy/`.

---

### Task 1: Lifecycle, Template, and Catalog Registration

**Files:**
- Modify: `runtime/strategy_lifecycle.py`
- Modify: `runtime/strategy_templates.py`
- Modify: `runtime/strategy_catalog.py`
- Modify: `runtime/strategy_instance_catalog.py`
- Test: `tests/test_strategy_lifecycle.py`
- Test: `tests/test_strategy_catalog.py`

**Interfaces:**
- Produces status: `research_observation`
- Produces template ID: `opportunity_observer`
- Produces strategy ID: `innovative_drug_globalization_observer_v0`

- [ ] **Step 1: Write failing lifecycle tests**

Add to `tests/test_strategy_lifecycle.py`:

```python
def test_research_observation_is_runnable_but_separate_from_paper(tmp_path: Path) -> None:
    """观察策略允许每日运行，但状态语义不同于 paper。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    repository.upsert_strategy_instance(
        {
            "strategy_id": "observer",
            "name": "Observer",
            "template_id": "opportunity_observer",
            "status": "research_observation",
            "enabled": True,
            "universe": "opportunity_theme:innovative_drug_globalization",
            "filters": ["exclude_rejected", "exclude_mature"],
            "factors": [],
            "construction": {"top_n": 5, "weighting": "equal_weight"},
            "benchmark": "510300",
        }
    )

    runnable = repository.list_runnable_strategy_instances()

    assert [item["strategy_id"] for item in runnable] == ["observer"]
```

Update the existing `test_list_runnable_strategy_instances_filters_lifecycle_status` expected IDs to include a seeded `research_observation` instance after implementation.

- [ ] **Step 2: Run lifecycle test and confirm failure**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q tests/test_strategy_lifecycle.py
```

Expected before implementation: FAIL with unknown status or non-runnable status for `research_observation`.

- [ ] **Step 3: Implement lifecycle status**

In `runtime/strategy_lifecycle.py`, set:

```python
RUNNABLE_STATUSES = {"research_observation", "paper", "shadow_live", "live"}
VALID_STATUSES = {"draft", "research", "research_observation", "paper", "shadow_live", "live", "paused", "retired"}
ALLOWED_TRANSITIONS = {
    "draft": {"research", "research_observation", "paused", "retired"},
    "research": {"research_observation", "paper", "paused", "retired"},
    "research_observation": {"paper", "paused", "retired"},
    "paper": {"shadow_live", "paused", "retired"},
    "shadow_live": {"live", "paused", "retired"},
    "live": {"paused", "retired"},
    "paused": {"research_observation", "paper", "retired"},
    "retired": set(),
}
```

In `validate_strategy_for_run()`, keep current checks but skip factor-contract validation when `template_id == "opportunity_observer"`:

```python
missing = list(contract_validation.get("missing_factors") or [])
if missing and str(strategy.get("template_id") or "") != "opportunity_observer":
    raise StrategyLifecycleError(f"missing factor contracts: {missing}")
```

- [ ] **Step 4: Register template and catalogs**

Append to `runtime/strategy_templates.py`:

```python
{
    "template_id": "opportunity_observer",
    "name": "产业机会观察策略",
    "description": "把投研机会主题转为每日观察组合和净值曲线，不生成交易建议。",
    "required_sections": ["universe", "construction", "benchmark"],
    "supported_status": ["research_observation", "paused", "retired"],
}
```

Add to `runtime/strategy_catalog.py`:

```python
def register_innovative_drug_observer_v0(repository: SystemRepository) -> None:
    """登记创新药出海观察策略，不生成交易调仓。"""
    repository.upsert_strategy(
        strategy_id="innovative_drug_globalization_observer_v0",
        name="创新药出海观察策略 V0",
        status="research_observation",
        strategy_type="opportunity_observer",
        description="基于创新药出海投研观察池生成Top5等权观察组合，仅用于研究观察。",
        config={
            "theme_id": "innovative_drug_globalization",
            "top_n": 5,
            "weighting": "equal_weight",
            "exclude_mature": True,
            "adjust_policy": "qfq",
            "trade_policy": "observation_only",
        },
    )
```

Call `register_innovative_drug_observer_v0(repository)` from `register_builtin_strategies()`.

Add to `runtime/strategy_instance_catalog.py`:

```python
repository.upsert_strategy_instance(
    {
        "strategy_id": "innovative_drug_globalization_observer_v0",
        "name": "创新药出海观察策略 V0",
        "template_id": "opportunity_observer",
        "status": "research_observation",
        "enabled": True,
        "universe": "opportunity_theme:innovative_drug_globalization",
        "filters": ["verified_opportunity_stock", "exclude_rejected", "exclude_mature", "qfq"],
        "factors": [],
        "construction": {"top_n": 5, "weighting": "equal_weight"},
        "risk_overlay": "observation_only",
        "benchmark": "510300",
        "config": {
            "theme_id": "innovative_drug_globalization",
            "exclude_mature": True,
            "trade_policy": "observation_only",
        },
    }
)
```

- [ ] **Step 5: Add catalog tests**

Add to `tests/test_strategy_catalog.py`:

```python
def test_register_builtin_strategies_exposes_innovative_drug_observer(tmp_path: Path) -> None:
    """内置策略目录应暴露创新药出海观察策略。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_builtin_strategies(repository)

    definition = repository.load_strategy_definition("innovative_drug_globalization_observer_v0")
    assert definition is not None
    assert definition["status"] == "research_observation"
    assert definition["strategy_type"] == "opportunity_observer"
    assert definition["config"]["trade_policy"] == "observation_only"
```

- [ ] **Step 6: Run tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q tests/test_strategy_lifecycle.py tests/test_strategy_catalog.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/strategy_lifecycle.py runtime/strategy_templates.py runtime/strategy_catalog.py runtime/strategy_instance_catalog.py tests/test_strategy_lifecycle.py tests/test_strategy_catalog.py
git commit -m "feat: register innovative drug observation strategy"
```

---

### Task 2: Opportunity Observer Runner

**Files:**
- Create: `strategies/opportunity_observer_runner.py`
- Test: `tests/test_opportunity_observer_runner.py`

**Interfaces:**
- Consumes strategy instance dict with `config.theme_id`, `construction.top_n`, and `config.exclude_mature`.
- Produces `run_opportunity_observer_instance(instance: dict[str, Any], paths: RuntimePaths) -> dict[str, Any]`.
- Writes monitoring history through `MonitoringRepository.upsert_strategy_daily`.
- Writes state through existing `strategy_instance_state` and `strategy_instance_holdings` tables.

- [ ] **Step 1: Write failing runner test**

Create `tests/test_opportunity_observer_runner.py`:

```python
from pathlib import Path

import pandas as pd

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from strategies.opportunity_observer_runner import run_opportunity_observer_instance


def _paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths(root=tmp_path)


def test_opportunity_observer_selects_top5_equal_weight_and_excludes_mature(tmp_path: Path, monkeypatch) -> None:
    """观察策略应按优先级选Top5，成熟样本默认不进入组合。"""
    paths = _paths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_opportunity_theme({"theme_id": "innovative_drug_globalization", "name": "创新药出海"})
    for symbol, level, score in [
        ("688235.SH", "S", 80.0),
        ("688180.SH", "A", 70.0),
        ("603259.SH", "A", 65.0),
        ("600276.SH", "B", 50.0),
        ("688331.SH", "成熟", 90.0),
        ("000001.SZ", "B", 40.0),
    ]:
        repository.upsert_opportunity_stock(
            {
                "theme_id": "innovative_drug_globalization",
                "symbol": symbol,
                "name": symbol,
                "status": "active",
                "watch_level": level,
                "verification_status": "verified",
                "evidence": {"priority": {"score": score}, "opportunity_phase": "LateConfirmed" if level == "成熟" else "Confirming"},
                "metrics": {"latest_close": 10.0 + score / 100.0},
                "last_monitor_date": "20260706",
            }
        )
    monkeypatch.setattr(
        "strategies.opportunity_observer_runner._load_benchmark_nav",
        lambda paths, benchmark, trade_date: 1.0,
    )

    result = run_opportunity_observer_instance(
        {
            "strategy_id": "innovative_drug_globalization_observer_v0",
            "name": "创新药出海观察策略 V0",
            "benchmark": "510300",
            "construction": {"top_n": 5, "weighting": "equal_weight"},
            "config": {"theme_id": "innovative_drug_globalization", "exclude_mature": True},
        },
        paths,
    )

    state = repository.load_strategy_instance_state("innovative_drug_globalization_observer_v0")
    assert result["selected_count"] == 5
    assert {item["symbol"] for item in state["holdings"]} == {"688235.SH", "688180.SH", "603259.SH", "600276.SH", "000001.SZ"}
    assert all(round(item["weight"], 6) == 0.2 for item in state["holdings"])
    assert "688331.SH" not in {item["symbol"] for item in state["holdings"]}
    latest = MonitoringRepository(paths.monitoring_path).load_latest_strategy_metrics("innovative_drug_globalization_observer_v0")
    assert latest is not None
    assert latest["exposure"] == 1.0
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q tests/test_opportunity_observer_runner.py
```

Expected: FAIL because `strategies.opportunity_observer_runner` does not exist.

- [ ] **Step 3: Implement runner**

Create `strategies/opportunity_observer_runner.py`:

```python
"""产业机会观察策略运行器。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def run_opportunity_observer_instance(instance: dict[str, Any], paths: RuntimePaths) -> dict[str, Any]:
    """运行观察策略，生成观察组合和净值曲线，不生成交易建议。"""
    repository = SystemRepository(paths.system_state_path)
    monitoring = MonitoringRepository(paths.monitoring_path)
    strategy_id = str(instance["strategy_id"])
    trade_date = datetime.now().strftime("%Y%m%d")
    run_dir = paths.runs_dir / trade_date
    run_dir.mkdir(parents=True, exist_ok=True)
    theme_id = str((instance.get("config") or {}).get("theme_id") or "").strip()
    if not theme_id:
        raise ValueError("opportunity observer requires config.theme_id")
    selected, excluded = _select_holdings(repository.load_opportunity_theme(theme_id), instance)
    nav, daily_return = _next_nav(monitoring, strategy_id)
    benchmark_id = str(instance.get("benchmark") or "510300")
    benchmark_nav = _load_benchmark_nav(paths, benchmark_id, trade_date)
    frame = _metrics_frame(instance, trade_date, nav, daily_return, benchmark_id, benchmark_nav, len(selected))
    monitoring.upsert_strategy_daily(frame)
    _write_state(repository, strategy_id, trade_date, nav, selected)
    _write_artifacts(run_dir, strategy_id, trade_date, selected, excluded, frame.iloc[0].to_dict())
    repository.record_strategy_run(strategy_id, trade_date, "SUCCESS", run_dir, f"observation selected {len(selected)} symbols")
    return {"strategy_id": strategy_id, "trade_date": trade_date, "selected_count": len(selected), "nav": nav}


def _select_holdings(theme: dict[str, Any], instance: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = dict(instance.get("config") or {})
    construction = dict(instance.get("construction") or {})
    top_n = int(construction.get("top_n") or 5)
    exclude_mature = bool(config.get("exclude_mature", True))
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for stock in theme.get("stocks", []):
        level = str(stock.get("watch_level") or "")
        evidence = stock.get("evidence") if isinstance(stock.get("evidence"), dict) else {}
        priority = evidence.get("priority") if isinstance(evidence.get("priority"), dict) else {}
        row = {
            "symbol": str(stock.get("symbol") or ""),
            "name": str(stock.get("name") or ""),
            "watch_level": level,
            "priority_score": float(priority.get("score") or 0.0),
            "reason": "；".join(priority.get("reasons") or []),
            "last_close": float((stock.get("metrics") or {}).get("latest_close") or 0.0),
        }
        if stock.get("status") != "active" or stock.get("verification_status") != "verified":
            row["exclude_reason"] = "未通过正式入池校验"
            excluded.append(row)
            continue
        if level == "淘汰":
            row["exclude_reason"] = "观察级别为淘汰"
            excluded.append(row)
            continue
        if exclude_mature and level == "成熟":
            row["exclude_reason"] = "成熟样本默认不进入观察组合"
            excluded.append(row)
            continue
        candidates.append(row)
    candidates.sort(key=lambda item: (-float(item["priority_score"]), str(item["symbol"])))
    selected = candidates[:top_n]
    weight = 1.0 / len(selected) if selected else 0.0
    for item in selected:
        item["weight"] = weight
    return selected, excluded


def _next_nav(monitoring: MonitoringRepository, strategy_id: str) -> tuple[float, float]:
    history = monitoring.load_strategy_history(strategy_id)
    if history.empty:
        return 1.0, 0.0
    latest = float(history.iloc[-1]["nav"])
    return latest, 0.0


def _metrics_frame(
    instance: dict[str, Any],
    trade_date: str,
    nav: float,
    daily_return: float,
    benchmark_id: str,
    benchmark_nav: float,
    selected_count: int,
) -> pd.DataFrame:
    cumulative = nav - 1.0
    benchmark_return = benchmark_nav - 1.0
    return pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "strategy_id": instance["strategy_id"],
                "strategy_name": instance["name"],
                "nav": nav,
                "daily_return": daily_return,
                "cumulative_return": cumulative,
                "benchmark_id": benchmark_id,
                "benchmark_nav": benchmark_nav,
                "benchmark_return": benchmark_return,
                "excess_return": cumulative - benchmark_return,
                "drawdown": 0.0,
                "max_drawdown": 0.0,
                "volatility_20": 0.0,
                "volatility_60": 0.0,
                "sharpe_rolling": 0.0,
                "exposure": 1.0 if selected_count else 0.0,
                "turnover_notional": 0.0,
                "total_execution_cost": 0.0,
                "failed_order_count": 0,
            }
        ]
    )


def _write_state(repository: SystemRepository, strategy_id: str, trade_date: str, nav: float, holdings: list[dict[str, Any]]) -> None:
    with repository._connect() as con:
        con.execute(
            """
            INSERT INTO strategy_instance_state(strategy_id, trade_date, nav)
            VALUES (?, ?, ?)
            ON CONFLICT(strategy_id) DO UPDATE SET
                trade_date=excluded.trade_date, nav=excluded.nav, modified_at=CURRENT_TIMESTAMP
            """,
            [strategy_id, trade_date, nav],
        )
        con.execute("DELETE FROM strategy_instance_holdings WHERE strategy_id = ?", [strategy_id])
        con.executemany(
            "INSERT INTO strategy_instance_holdings(strategy_id, symbol, weight, last_close) VALUES (?, ?, ?, ?)",
            [(strategy_id, item["symbol"], float(item["weight"]), float(item["last_close"])) for item in holdings],
        )


def _write_artifacts(
    run_dir: Path,
    strategy_id: str,
    trade_date: str,
    selected: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> None:
    selected_path = run_dir / f"{strategy_id}_snapshot.csv"
    metrics_path = run_dir / f"{strategy_id}_metrics.json"
    report_path = run_dir / f"{strategy_id}_report.md"
    pd.DataFrame(selected).to_csv(selected_path, index=False)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_report_text(trade_date, selected, excluded), encoding="utf-8")


def _report_text(trade_date: str, selected: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> str:
    lines = [
        "# 创新药出海观察策略 V0",
        "",
        f"- 交易日：{trade_date}",
        "- 状态：观察策略，不构成调仓建议",
        f"- 入选数量：{len(selected)}",
        f"- 排除数量：{len(excluded)}",
    ]
    return "\\n".join(lines)


def _load_benchmark_nav(_paths: RuntimePaths, _benchmark: str, _trade_date: str) -> float:
    """读取基准净值，V0 先用1.0兜底，后续可接入已有基准曲线。"""
    return 1.0
```

- [ ] **Step 4: Run runner test**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q tests/test_opportunity_observer_runner.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add strategies/opportunity_observer_runner.py tests/test_opportunity_observer_runner.py
git commit -m "feat: add opportunity observer runner"
```

---

### Task 3: Batch Runner and Daily Pipeline Integration

**Files:**
- Modify: `runtime/strategy_batch_runner.py`
- Modify: `runtime/daily_pipeline.py`
- Test: `tests/test_strategy_batch_runner.py`
- Test: `tests/test_daily_pipeline.py`

**Interfaces:**
- Consumes `run_opportunity_observer_instance(instance, paths)`.
- Produces batch result message: `observation selected N symbols, nav X`.
- Produces operation summary label: `观察策略，不构成调仓建议`.

- [ ] **Step 1: Write failing batch dispatch test**

Add to `tests/test_strategy_batch_runner.py`:

```python
def test_strategy_batch_dispatches_opportunity_observer(tmp_path: Path, monkeypatch) -> None:
    """批处理应能分发观察策略模板。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_strategy_instance(
        {
            "strategy_id": "innovative_drug_globalization_observer_v0",
            "name": "创新药出海观察策略 V0",
            "template_id": "opportunity_observer",
            "status": "research_observation",
            "enabled": True,
            "universe": "opportunity_theme:innovative_drug_globalization",
            "filters": [],
            "factors": [],
            "construction": {"top_n": 5},
            "benchmark": "510300",
            "config": {"theme_id": "innovative_drug_globalization"},
        }
    )
    monkeypatch.setattr(
        "runtime.strategy_batch_runner.run_opportunity_observer_instance",
        lambda instance, paths: {"selected_count": 3, "nav": 1.0},
    )

    result = run_enabled_strategy_instances(paths)

    assert result["success_count"] == 1
    assert result["results"][0]["message"] == "observation selected 3 symbols, nav 1.000000"
```

- [ ] **Step 2: Implement batch dispatch**

In `runtime/strategy_batch_runner.py`:

```python
from strategies.opportunity_observer_runner import run_opportunity_observer_instance
```

Add before unsupported template branch:

```python
if command is None and instance.get("template_id") == "opportunity_observer":
    try:
        result = run_opportunity_observer_instance(instance, paths)
        message = f"observation selected {result['selected_count']} symbols, nav {result['nav']:.6f}"
        _send_native_notification(instance, f"{message}\\n观察策略，不构成调仓建议", push, bark_url)
        return {"strategy_id": strategy_id, "status": "SUCCESS", "message": message}
    except Exception as exc:
        message = str(exc)
        repository.record_strategy_run(strategy_id, trade_date, "FAILED", paths.runs_dir / trade_date, message)
        _send_native_notification(instance, f"FAILED: {message}", push, bark_url)
        return {"strategy_id": strategy_id, "status": "FAILED", "message": message}
```

- [ ] **Step 3: Update operation summary text**

In `runtime/daily_pipeline.py`, inside `_format_strategy_operation_block()`, add a branch based on strategy ID or name:

```python
if str(metrics.get("strategy_id") or "").endswith("_observer_v0"):
    return [
        str(metrics.get("strategy_name") or metrics.get("strategy_id")),
        "- 状态：观察策略，不构成调仓建议",
        f"- 观察仓位：{float(metrics.get('exposure', 0.0)):.2%}",
        f"- 当日收益：{float(metrics.get('daily_return', 0.0)):.2%}",
        f"- 当前回撤：{float(metrics.get('drawdown', 0.0)):.2%}",
        "- 操作建议：不操作",
    ]
```

- [ ] **Step 4: Run tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q tests/test_strategy_batch_runner.py tests/test_daily_pipeline.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/strategy_batch_runner.py runtime/daily_pipeline.py tests/test_strategy_batch_runner.py tests/test_daily_pipeline.py
git commit -m "feat: run opportunity observers in daily batch"
```

---

### Task 4: Frontend Observation Status Display

**Files:**
- Modify: `frontend/src/entities/strategy/lifecycle.ts`
- Modify: `frontend/src/entities/strategy/lifecycle.test.ts`
- Modify: `frontend/src/pages/strategies/StrategiesPage.tsx`
- Test: `frontend/src/entities/strategy/lifecycle.test.ts`

**Interfaces:**
- Consumes strategy instance status `research_observation`.
- Produces UI text: `观察中，不可交易`.

- [ ] **Step 1: Write lifecycle tests**

Modify `frontend/src/entities/strategy/lifecycle.test.ts`:

```typescript
import { expect, test } from "vitest";

import { lifecycleTone, transitionCandidates } from "./lifecycle";

test("transitionCandidates supports research observation status", () => {
  expect(transitionCandidates("research_observation").map((item) => item.target_status)).toEqual(["paper", "paused", "retired"]);
});

test("lifecycleTone treats research observation as neutral", () => {
  expect(lifecycleTone("research_observation")).toBe("neutral");
});
```

- [ ] **Step 2: Implement lifecycle mapping**

In `frontend/src/entities/strategy/lifecycle.ts`:

```typescript
research_observation: [
  { target_status: "paper", label: "进入模拟盘" },
  { target_status: "paused", label: "暂停" },
  { target_status: "retired", label: "归档" }
],
```

Keep `lifecycleTone("research_observation")` neutral by not adding it to success/warning/danger sets.

- [ ] **Step 3: Add observation banner in strategy page**

In `frontend/src/pages/strategies/StrategiesPage.tsx`, after selected instance is computed:

```typescript
const selectedIsObservation = selectedInstance?.status === "research_observation";
```

Before `StrategyOperationsPanel`, render:

```tsx
{selectedIsObservation ? (
  <section className="panel">
    <div className="detail-heading">
      <div>
        <h2>观察策略</h2>
        <p>该策略仅用于投研观察和净值跟踪，不构成调仓建议，不进入真实组合账户。</p>
      </div>
      <span className="status neutral">观察中，不可交易</span>
    </div>
  </section>
) : null}
```

Pass `accountMessage` normally. Do not hide account panels in V0; the banner is enough to prevent误读.

- [ ] **Step 4: Run frontend tests**

Run:

```bash
cd frontend
npm test -- --run frontend/src/entities/strategy/lifecycle.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/entities/strategy/lifecycle.ts frontend/src/entities/strategy/lifecycle.test.ts frontend/src/pages/strategies/StrategiesPage.tsx
git commit -m "feat: show observation strategy lifecycle"
```

---

### Task 5: End-to-End Verification and Documentation

**Files:**
- Modify if needed: `tests/test_local_api_service.py`
- Modify if needed: `docs/superpowers/specs/2026-07-06-innovative-drug-observation-strategy-design.md`

**Interfaces:**
- Verifies API lists observation strategy and instance.
- Verifies runner creates run artifacts.

- [ ] **Step 1: Add API visibility test**

In `tests/test_local_api_service.py`, extend strategy API tests or add:

```python
def test_local_api_exposes_innovative_drug_observer(tmp_path: Path) -> None:
    """本地 API 应暴露创新药观察策略定义和实例。"""
    service = LocalApiService(paths=RuntimePaths(root=tmp_path))

    strategies = service.list_strategies()
    instances = service.list_strategy_instances()

    assert any(item["strategy_id"] == "innovative_drug_globalization_observer_v0" for item in strategies)
    observer = next(item for item in instances if item["strategy_id"] == "innovative_drug_globalization_observer_v0")
    assert observer["status"] == "research_observation"
    assert observer["template_id"] == "opportunity_observer"
```

Use actual service method names from `api/service.py`; if names are `strategies()` or `strategy_instances()`, use those exact methods.

- [ ] **Step 2: Run backend focused tests**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q \
  tests/test_strategy_lifecycle.py \
  tests/test_strategy_catalog.py \
  tests/test_opportunity_observer_runner.py \
  tests/test_strategy_batch_runner.py \
  tests/test_daily_pipeline.py \
  tests/test_local_api_service.py
```

Expected: PASS.

- [ ] **Step 3: Run full backend test suite**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Run frontend suite and build**

Run:

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: tests PASS and Vite build succeeds.

- [ ] **Step 5: Manual smoke run**

Run:

```bash
/Users/admin/recommend_analysis/.venv/bin/python3 scripts/run_strategy_batch.py
```

Expected output includes `innovative_drug_globalization_observer_v0=SUCCESS` or JSON result with selected count. Confirm files exist:

```bash
ls runs/$(date +%Y%m%d)/innovative_drug_globalization_observer_v0_*
```

- [ ] **Step 6: Commit final polish**

```bash
git status --short
git add tests/test_local_api_service.py docs/superpowers/specs/2026-07-06-innovative-drug-observation-strategy-design.md
git commit -m "test: verify innovative drug observer integration"
```

Only commit files actually changed in this task.

---

## Self-Review Notes

- Spec coverage: lifecycle, registration, daily run, monitoring writes, frontend visibility, notification wording, and non-trading guards are covered by Tasks 1-5.
- Scope intentionally excludes BD event tables, overseas revenue, pipeline data, and strategy optimization.
- The runner starts with a conservative initial NAV rule based on existing monitor history. If richer return attribution is needed later, it should be a separate V1 plan because it requires historical daily reconstructed holdings.
- Observation strategy dispatch is generic through `opportunity_observer`, so future opportunity themes can reuse the same runner by changing `config.theme_id`.
