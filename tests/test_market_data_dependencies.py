"""平台行情依赖配置测试。"""

from __future__ import annotations

import json
from pathlib import Path

from data.market_data_dependencies import (
    load_market_data_dependencies,
    validate_fund_incremental_coverage,
)


class DateStoreStub:
    """测试用逐标的最新日期存储。"""

    def __init__(self, dates: dict[tuple[str, str], str | None]) -> None:
        self.dates = dates

    def latest_date(self, table: str, ts_code: str) -> str | None:
        return self.dates.get((table, ts_code))


def test_default_dependencies_include_defensive_funds() -> None:
    """跨资产研究所需基金必须进入每日固定行情依赖。"""
    dependencies = load_market_data_dependencies()

    assert dependencies.fund_symbols == (
        "510300.SH",
        "518880.SH",
        "511010.SH",
        "513500.SH",
    )


def test_dependency_loader_rejects_duplicate_symbols(tmp_path: Path) -> None:
    """重复代码会造成更新与质量门禁口径不一致，必须立即失败。"""
    path = tmp_path / "dependencies.json"
    path.write_text(
        json.dumps(
            {
                "funds": [
                    {"symbol": "510300.SH", "enabled": True},
                    {"symbol": "510300.SH", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        load_market_data_dependencies(path)
    except ValueError as exc:
        assert "重复代码" in str(exc)
    else:
        raise AssertionError("重复基金代码应被拒绝")


def test_symbol_level_coverage_detects_stale_defensive_asset() -> None:
    """整表最新不代表每只资产最新，逐标的门禁必须抓住局部滞后。"""
    store = DateStoreStub(
        {
            ("fund_daily", "510300.SH"): "20260723",
            ("fund_adj", "510300.SH"): "20260723",
            ("fund_daily", "518880.SH"): "20260722",
            ("fund_adj", "518880.SH"): "20260723",
        }
    )

    issues = validate_fund_incremental_coverage(
        store,
        ["510300.SH", "518880.SH"],
        "20260723",
    )

    assert issues == ["518880.SH.fund_daily 最新20260722，要求20260723"]
