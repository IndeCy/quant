"""Factor Computation Runner 测试。"""

from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from runtime.factor_computation_runner import FactorComputationError, run_factor_computation
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


class StaticCalculator:
    """测试计算器，返回固定因子分数。"""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def compute(self, contract: dict, trade_date: str) -> pd.DataFrame:
        assert contract["factor_id"] == "roa"
        assert trade_date == "20260702"
        return self.frame.copy()


def _register_roa_contract(paths: RuntimePaths) -> None:
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_factor_contract(
        {
            "factor_id": "roa",
            "name": "ROA",
            "category": "quality",
            "direction": "higher_is_better",
            "source": "fina_indicator",
            "frequency": "annual",
            "value_type": "numeric",
            "as_of_policy": "financial_announcement",
            "as_of_field": "f_ann_date",
            "effective_date_field": "trade_date",
            "input_datasets": ["fina_indicator_duckdb"],
            "input_fields": ["roa"],
            "output_fields": ["trade_date", "symbol", "factor_value"],
            "status": "active",
        }
    )


def test_factor_computation_runner_writes_scores_idempotently(tmp_path: Path) -> None:
    """同一因子同一日期重复计算应替换旧结果，不产生重复分数。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _register_roa_contract(paths)
    frame = pd.DataFrame(
        [
            {"symbol": "000001.SZ", "value": 0.10, "close": 10.0},
            {"symbol": "000002.SZ", "value": 0.12, "close": 20.0},
        ]
    )
    calculator = StaticCalculator(frame)

    first = run_factor_computation(paths, "roa", "20260702", calculator)
    second = run_factor_computation(paths, "roa", "20260702", calculator)

    with sqlite3.connect(paths.factor_scores_path) as con:
        rows = con.execute("SELECT trade_date, symbol, factor_id, value FROM factor_scores ORDER BY symbol").fetchall()
        prices = con.execute("SELECT trade_date, symbol, close FROM daily_prices ORDER BY symbol").fetchall()
    assert first["written_count"] == 2
    assert second["written_count"] == 2
    assert rows == [
        ("20260702", "000001.SZ", "roa", 0.10),
        ("20260702", "000002.SZ", "roa", 0.12),
    ]
    assert prices == [("20260702", "000001.SZ", 10.0), ("20260702", "000002.SZ", 20.0)]


def test_factor_computation_runner_requires_factor_contract(tmp_path: Path) -> None:
    """没有 Factor Contract 的因子不能计算入库。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    calculator = StaticCalculator(pd.DataFrame([{"symbol": "000001.SZ", "value": 0.10}]))

    with pytest.raises(FactorComputationError, match="factor contract not found"):
        run_factor_computation(paths, "roa", "20260702", calculator)


def test_factor_computation_runner_requires_symbol_and_value(tmp_path: Path) -> None:
    """计算结果必须至少包含 symbol 和 value。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _register_roa_contract(paths)
    calculator = StaticCalculator(pd.DataFrame([{"symbol": "000001.SZ", "score": 0.10}]))

    with pytest.raises(FactorComputationError, match="value"):
        run_factor_computation(paths, "roa", "20260702", calculator)
