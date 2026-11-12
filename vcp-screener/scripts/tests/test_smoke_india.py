"""End-to-end smoke test of screen_vcp with a fake India client (no network)."""
import glob
import json
import math
import os
import sys
import tempfile
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import screen_vcp  # noqa: E402


def bars(n=300, start=100.0, drift=0.004):
    out = []
    d = date(2026, 11, 10)
    price = start * math.exp(drift * n)
    for i in range(n):
        wiggle = 1 + 0.01 * math.sin(i / 3.0)
        c = price * wiggle
        out.append({"date": (d - timedelta(days=i)).isoformat(), "open": c * 0.995,
                    "high": c * 1.01, "low": c * 0.985, "close": c, "adjClose": c,
                    "volume": 500000})
        price /= math.exp(drift)
    return out


class FakeClient:
    def __init__(self, *a, **k):
        pass

    def get_historical_prices(self, symbol, days=365):
        return {"symbol": symbol, "historical": bars()[:days]}

    def get_batch_quotes(self, symbols):
        out = {}
        for s in symbols:
            h = bars()
            out[s] = {"symbol": s, "price": h[0]["close"], "yearHigh": max(b["high"] for b in h[:252]),
                      "yearLow": min(b["low"] for b in h[:252]), "avgVolume": 500000,
                      "volume": 500000, "marketCap": None, "name": s, "exchange": "NSE"}
        return out

    def get_universe_rows(self, name="nifty500"):
        return [{"Symbol": "AAA", "Company Name": "Aaa Ltd", "Industry": "Metals"}]

    def get_api_stats(self):
        return {"api_calls_made": 0, "cache_entries": 0}


def test_screen_vcp_runs_end_to_end():
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(screen_vcp, "FMPClient", FakeClient):
        argv = ["screen_vcp.py", "--universe", "AAA", "BBB", "--output-dir", tmp]
        with mock.patch.object(sys, "argv", argv):
            screen_vcp.main()
        files = glob.glob(os.path.join(tmp, "vcp_screener_*.json"))
        assert len(files) == 1
        data = json.load(open(files[0], encoding="utf-8"))
        assert data["metadata"]["funnel"]["universe"] == 2
        assert glob.glob(os.path.join(tmp, "vcp_screener_*.md"))


def test_pre_filter_uses_rupee_floor():
    q = {"price": 40, "yearHigh": 45, "yearLow": 20, "avgVolume": 500000}
    assert screen_vcp.pre_filter_stock(q)[0] is False
    q["price"] = 100
    q.update(yearHigh=110, yearLow=60)
    assert screen_vcp.pre_filter_stock(q)[0] is True
