import pandas as pd

from examples.quality_cleanup_audit import apply_quality_cleanup_filters


def test_apply_quality_cleanup_filters_removes_untrusted_records():
    frame = pd.DataFrame(
        {
            "symbol": ["GOOD", "YOUNG", "STOCK", "PAST_DELIST", "FUTURE_DELIST", "QTR"],
            "signal_date": ["20240131"] * 6,
            "list_date": ["20100101", "20230101", "20100101", "20100101", "20100101", "20100101"],
            "name": ["好公司", "新股", "*ST样本", "过去样本", "未来样本", "季度样本"],
            "st_name": [None, None, None, None, None, None],
            "list_status": ["L", "L", "L", "D", "D", "L"],
            "delist_date": [None, None, None, "20230101", "20250101", None],
            "end_date": ["20231231", "20231231", "20231231", "20231231", "20231231", "20230930"],
            "roe": [10.0] * 6,
            "roa": [5.0] * 6,
            "ocf_to_or": [0.2] * 6,
        }
    )

    filtered = apply_quality_cleanup_filters(frame, quantile_filter=False)

    assert filtered["symbol"].tolist() == ["GOOD", "FUTURE_DELIST"]


def test_apply_quality_cleanup_filters_removes_roe_roa_extremes():
    frame = pd.DataFrame(
        {
            "symbol": [f"S{i}" for i in range(10)],
            "signal_date": ["20240131"] * 10,
            "list_date": ["20100101"] * 10,
            "name": [f"样本{i}" for i in range(10)],
            "st_name": [None] * 10,
            "list_status": ["L"] * 10,
            "delist_date": [None] * 10,
            "end_date": ["20231231"] * 10,
            "roe": [-100.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 100.0],
            "roa": [-50.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 50.0],
            "ocf_to_or": [0.2] * 10,
        }
    )

    filtered = apply_quality_cleanup_filters(frame, quantile_filter=True)

    assert "S0" not in filtered["symbol"].tolist()
    assert "S9" not in filtered["symbol"].tolist()
