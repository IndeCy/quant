from __future__ import annotations

import urllib.request

from backtest.fetcher import get_realtime_quote


class _FakeResponse:
    def read(self) -> bytes:
        fields = [""] * 82
        fields[1] = "国债ETF国泰"
        fields[3] = "140.869"
        fields[4] = "140.874"
        fields[5] = "140.874"
        fields[30] = "20260729144815"
        fields[77] = "0.12"
        fields[78] = "140.7000"
        fields[81] = "140.6900"
        return f'v_sh511010="{"~".join(fields)}";'.encode("gbk")


def test_realtime_quote_routes_shanghai_funds_to_sh_prefix(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> _FakeResponse:
        requested_urls.append(request.full_url)
        assert timeout == 10
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    quotes = get_realtime_quote(["511010", "518880", "600000", "159915", "830001"])

    assert requested_urls == [
        "https://qt.gtimg.cn/q=sh511010,sh518880,sh600000,sz159915,bj830001"
    ]
    assert quotes["511010"]["open"] == 140.874
    assert quotes["511010"]["quote_time"] == "20260729144815"
    assert quotes["511010"]["premium_pct"] == 0.12
    assert quotes["511010"]["reference_nav"] == 140.7
    assert quotes["511010"]["previous_nav"] == 140.69
