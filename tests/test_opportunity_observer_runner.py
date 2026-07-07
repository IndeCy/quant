"""产业机会观察策略 runner 测试。"""

from pathlib import Path

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from strategies.opportunity_observer_runner import run_opportunity_observer_instance


def _paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths(root=tmp_path)


def _seed_stock(repository: SystemRepository, symbol: str, level: str, score: float, latest_close: float = 10.0) -> None:
    """写入一只已验证机会池股票。"""
    repository.upsert_opportunity_stock(
        {
            "theme_id": "innovative_drug_globalization",
            "symbol": symbol,
            "name": symbol,
            "status": "active",
            "watch_level": level,
            "verification_status": "verified",
            "evidence": {
                "priority": {"score": score, "reasons": [f"优先级 {score:.0f}"]},
                "opportunity_phase": "LateConfirmed" if level == "成熟" else "Confirming",
            },
            "metrics": {"latest_close": latest_close},
            "last_monitor_date": "20260706",
        }
    )


def test_opportunity_observer_selects_top5_equal_weight_and_excludes_mature(tmp_path: Path, monkeypatch) -> None:
    """观察策略应按优先级选 Top5，成熟样本默认不进入组合。"""
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
        _seed_stock(repository, symbol, level, score, 10.0 + score / 100.0)
    monkeypatch.setattr("strategies.opportunity_observer_runner._load_prices", lambda paths, trade_date, symbols: {})

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
    assert all(round(float(item["weight"]), 6) == 0.2 for item in state["holdings"])
    assert "688331.SH" not in {item["symbol"] for item in state["holdings"]}
    latest = MonitoringRepository(paths.monitoring_path).load_latest_strategy_metrics("innovative_drug_globalization_observer_v0")
    assert latest is not None
    assert float(latest["exposure"]) == 1.0


def test_opportunity_observer_accepts_requested_trade_date(tmp_path: Path, monkeypatch) -> None:
    """批处理补跑历史日期时，观察策略记录必须落到指定交易日。"""
    paths = _paths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_opportunity_theme({"theme_id": "innovative_drug_globalization", "name": "创新药出海"})
    _seed_stock(repository, "688235.SH", "S", 80.0, 10.0)
    monkeypatch.setattr("strategies.opportunity_observer_runner._today", lambda: "20260708")
    monkeypatch.setattr("strategies.opportunity_observer_runner._load_prices", lambda paths, trade_date, symbols: {"688235.SH": 10.0})

    result = run_opportunity_observer_instance(
        {
            "strategy_id": "innovative_drug_globalization_observer_v0",
            "name": "创新药出海观察策略 V0",
            "benchmark": "510300",
            "construction": {"top_n": 1, "weighting": "equal_weight"},
            "config": {"theme_id": "innovative_drug_globalization", "exclude_mature": True},
        },
        paths,
        trade_date="20260707",
    )

    run = repository.get_run("innovative_drug_globalization_observer_v0", "20260707")
    latest = MonitoringRepository(paths.monitoring_path).load_latest_strategy_metrics("innovative_drug_globalization_observer_v0")
    assert result["trade_date"] == "20260707"
    assert run is not None
    assert latest is not None
    assert latest["trade_date"] == "20260707"


def test_opportunity_observer_rolls_nav_from_previous_holdings(tmp_path: Path, monkeypatch) -> None:
    """观察净值应由上一期观察持仓的最新价格滚动，不应每天固定为 1。"""
    paths = _paths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_opportunity_theme({"theme_id": "innovative_drug_globalization", "name": "创新药出海"})
    _seed_stock(repository, "688235.SH", "S", 80.0, 10.0)
    instance = {
        "strategy_id": "innovative_drug_globalization_observer_v0",
        "name": "创新药出海观察策略 V0",
        "benchmark": "510300",
        "construction": {"top_n": 1, "weighting": "equal_weight"},
        "config": {"theme_id": "innovative_drug_globalization", "exclude_mature": True},
    }
    monkeypatch.setattr("strategies.opportunity_observer_runner._today", lambda: "20260706")
    monkeypatch.setattr("strategies.opportunity_observer_runner._load_prices", lambda paths, trade_date, symbols: {"688235.SH": 10.0})
    first = run_opportunity_observer_instance(instance, paths)

    repository.update_opportunity_stock_monitor(
        "innovative_drug_globalization",
        "688235.SH",
        "S",
        {"latest_close": 11.0},
        "20260707",
        {"priority": {"score": 80.0, "reasons": ["继续观察"]}},
    )
    monkeypatch.setattr("strategies.opportunity_observer_runner._today", lambda: "20260707")
    monkeypatch.setattr("strategies.opportunity_observer_runner._load_prices", lambda paths, trade_date, symbols: {"688235.SH": 11.0})
    second = run_opportunity_observer_instance(instance, paths)

    assert first["nav"] == 1.0
    assert round(float(second["nav"]), 6) == 1.1
