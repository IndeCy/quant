"""QDII最新净值监控审计测试。"""

import pandas as pd

from examples import qdii_current_nav_monitoring_audit as audit


class FakeClient:
    def fetch(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": [symbol],
                "nav_date": ["20260727"],
                "unit_nav": [1.50],
            }
        )


def test_definition_is_read_only_and_does_not_replace_iopv() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["external_read"]["writes_production_database"] is False
    assert definition["does_not_replace_realtime_iopv"] is True
    assert definition["does_not_override_source_gate"] is True


def test_current_nav_loader_keeps_positive_latest_values() -> None:
    frame = audit.load_current_nav(FakeClient(), "20260728")

    assert set(frame["symbol"]) == set(audit.SYMBOLS)
    assert frame["unit_nav"].eq(1.50).all()
    assert frame["end_date"].eq("20260727").all()


def test_summary_matches_same_date_raw_close() -> None:
    nav = pd.DataFrame(
        {
            "symbol": list(audit.SYMBOLS),
            "end_date": ["20260727", "20260727"],
            "unit_nav": [1.50, 2.00],
        }
    )
    prices = pd.DataFrame(
        {
            "symbol": list(audit.SYMBOLS),
            "trade_date": ["20260727", "20260727"],
            "close": [1.53, 1.98],
        }
    )

    result = audit.summarize_observations(nav, prices, "20260728")

    assert result["nav_staleness_days"].eq(1).all()
    assert result["premium"].round(3).tolist() == [0.020, -0.010]
