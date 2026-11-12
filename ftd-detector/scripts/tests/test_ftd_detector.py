"""Offline CLI regressions through the real state machine and report writers."""

import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import copy
import json
from collections import Counter
from datetime import date, timedelta

import ftd_detector
import pytest
import urllib.request
from helpers import make_bar, make_rally_history


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def unexpected_request(*args, **kwargs):
        pytest.fail("FTD CLI fixtures must not make network requests")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", unexpected_request)


def market_history(*, peak=100, confirmed=True, invalidated=False):
    bars, _, _, ftd_idx = make_rally_history(
        peak=peak,
        rally_days=8,
        ftd_day=5 if confirmed else None,
        ftd_gain_pct=2.1,
    )
    if invalidated:
        bars.append(make_bar(bars[ftd_idx]["low"] - 0.1, volume=2_000_000))
    session = date(2026, 3, 2)
    for bar in bars:
        bar["date"] = session.isoformat()
        session += timedelta(days=1)
        while session.weekday() >= 5:
            session += timedelta(days=1)
    return list(reversed(bars))


class FixtureClient:
    def __init__(self, histories, quotes):
        self.histories = histories
        self.quotes = quotes
        self.calls = []

    def get_historical_prices(self, symbol, days):
        self.calls.append(("history", symbol, days))
        return self.histories[symbol]

    def get_quote(self, symbol):
        self.calls.append(("quote", symbol))
        return self.quotes[symbol]

    def get_api_stats(self):
        return {"api_calls_made": len(self.calls), "cache_entries": 0}


def install_client(monkeypatch, tmp_path, client, midcap=None):
    """Run main() with the fixture client and a fixed Midcap 150 composite."""
    monkeypatch.setattr(ftd_detector, "build_midcap_composite", lambda *a, **k: midcap or [])
    monkeypatch.setattr("sys.argv", ["ftd_detector.py", "--output-dir", str(tmp_path)])
    return lambda: ftd_detector.main(client=client)


def read_reports(tmp_path):
    json_paths = list(tmp_path.glob("ftd_detector_*.json"))
    md_paths = list(tmp_path.glob("ftd_detector_*.md"))
    assert len(json_paths) == len(md_paths) == 1
    assert json_paths[0].stem == md_paths[0].stem
    return json.loads(json_paths[0].read_text()), md_paths[0].read_text()


@pytest.mark.parametrize(
    "scenario,expected_state,expected_score",
    [
        ("dual", "FTD_CONFIRMED", 100),
        ("single", "FTD_CONFIRMED", 95),
        ("midcap_single", "FTD_CONFIRMED", 95),
        ("invalidated", "FTD_INVALIDATED", 0),
        ("window", "FTD_WINDOW", 0),
    ],
)
def test_main_writes_real_decision_reports(
    monkeypatch, tmp_path, scenario, expected_state, expected_score
):
    nifty50 = market_history(
        confirmed=scenario not in {"midcap_single", "window"},
        invalidated=scenario == "invalidated",
    )
    midcap = market_history(
        peak=400,
        confirmed=scenario not in {"single", "window"},
        invalidated=scenario == "invalidated",
    )
    histories = {"^NSEI": {"historical": nifty50}}
    original = copy.deepcopy(histories)
    client = FixtureClient(histories, {"^NSEI": [{"price": 101.25}]})
    run = install_client(monkeypatch, tmp_path, client, midcap)

    run()

    report, markdown = read_reports(tmp_path)
    assert Counter((call[0], call[1]) for call in client.calls) == Counter(
        {
            ("history", "^NSEI"): 1,
            ("quote", "^NSEI"): 1,
        }
    )
    assert histories == original
    assert report["metadata"]["api_calls"] == {"api_calls_made": 2, "cache_entries": 0}
    assert report["metadata"]["index_prices"] == {"nifty50": 101.25, "midcap": midcap[0]["close"]}
    assert "**Nifty 50:** Rs 101.25" in markdown
    assert f"**Midcap150:** Rs {midcap[0]['close']:.2f}" in markdown
    assert report["market_state"]["combined_state"] == expected_state
    assert report["market_state"]["dual_confirmation"] is (scenario == "dual")
    assert report["quality_score"]["total_score"] == expected_score
    assert f"**{expected_score}/100**" in markdown
    for key, history in [("nifty50", nifty50), ("midcap", midcap)]:
        index = report[key]
        assert index["current_price"] == history[0]["close"]
        assert index["swing_low"]["price"] == (95 if key == "nifty50" else 380)
        assert index["rally_attempt"]["day1_date"] == "2026-03-24"
        assert "rally_days" not in index["rally_attempt"]
        assert "_ftd_idx" not in index["ftd"]
    if scenario == "window":
        assert report["nifty50"]["ftd"]["ftd_detected"] is False
        assert report["quality_score"]["signal"] == "No FTD"
        assert "## FTD Signal" not in markdown
        assert "Do not buy ahead of FTD confirmation" in markdown
    else:
        confirmed_index = report["midcap"] if scenario == "midcap_single" else report["nifty50"]
        assert confirmed_index["ftd"]["ftd_date"] == "2026-03-30"
        assert confirmed_index["ftd"]["ftd_day_number"] == 5
        assert confirmed_index["ftd"]["gain_pct"] == 2.1
        assert "## FTD Signal" in markdown
    if scenario == "invalidated":
        invalidation = report["ftd_invalidation"]
        assert invalidation["invalidated"] is True
        assert invalidation["invalidation_date"] == "2026-04-03"
        assert invalidation["days_after_ftd"] == 4
        assert report["post_ftd_distribution"]["distribution_count"] == 1
        assert report["quality_score"]["signal"] == "Failed/Invalidated"
        assert report["quality_score"]["exposure_range"] == "0-25%"
        assert "Reduce exposure back to defensive levels" in markdown
        assert "Aggressively increase equity exposure" not in markdown
    elif scenario == "dual":
        assert "YES (Nifty 50 + Midcap 150)" in markdown
        assert report["ftd_invalidation"]["invalidated"] is False
    elif scenario == "single":
        assert "| **FTD Index** | Nifty 50 |" in markdown
        assert "YES (Nifty 50 + Midcap 150)" not in markdown
    elif scenario == "midcap_single":
        assert report["nifty50"]["ftd"]["ftd_detected"] is False
        assert report["midcap"]["ftd"]["ftd_detected"] is True
        assert report["market_state"]["dual_confirmation"] is False
        assert report["market_state"]["ftd_index"] == "Midcap 150"
        assert "| **FTD Index** | Midcap 150 |" in markdown
        assert "### Midcap 150 FTD" in markdown
        assert "### Nifty 50 FTD" not in markdown


@pytest.mark.parametrize("midcap_available", [True, False])
def test_missing_quotes_use_latest_historical_close_in_real_reports(
    monkeypatch, tmp_path, capsys, midcap_available
):
    nifty50 = market_history()
    midcap = market_history(peak=400) if midcap_available else []
    client = FixtureClient({"^NSEI": {"historical": nifty50}}, {"^NSEI": None})
    run = install_client(monkeypatch, tmp_path, client, midcap)

    run()

    report, markdown = read_reports(tmp_path)
    assert report["metadata"]["index_prices"] == {
        "nifty50": nifty50[0]["close"],
        "midcap": midcap[0]["close"] if midcap else None,
    }
    assert f"**Nifty 50:** Rs {nifty50[0]['close']:.2f}" in markdown
    output = capsys.readouterr().out
    assert output.count("Using historical close as current price") == 1
    if midcap_available:
        assert f"**Midcap150:** Rs {midcap[0]['close']:.2f}" in markdown
    else:
        assert "Midcap 150 data unavailable, using Nifty 50 only" in output
        assert report["midcap"]["current_price"] is None
        assert report["market_state"]["dual_confirmation"] is False
        assert report["market_state"]["ftd_index"] == "Nifty 50"
        assert "**Midcap150:**" not in markdown


@pytest.mark.parametrize("history", [None, {}, {"historical": []}])
def test_missing_mandatory_history_exits_without_reports(monkeypatch, tmp_path, capsys, history):
    client = FixtureClient({"^NSEI": history}, {})
    run = install_client(monkeypatch, tmp_path, client)
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 1
    assert "Cannot proceed without Nifty 50 data" in capsys.readouterr().err
    assert [(call[0], call[1]) for call in client.calls] == [("history", "^NSEI")]
    assert list(tmp_path.iterdir()) == []


def test_cli_parses_explicit_arguments(tmp_path):
    args = ftd_detector.parse_arguments(["--output-dir", str(tmp_path), "--max-symbols", "7"])
    assert args.output_dir == str(tmp_path)
    assert args.max_symbols == 7


def test_drop_incomplete_bar():
    from index_data import drop_incomplete_bar

    bars = [make_bar(100, volume=0, date="d2"), make_bar(99, volume=5, date="d1")]
    assert drop_incomplete_bar(bars)[0]["date"] == "d1"
    full = [make_bar(100, volume=7, date="d2"), make_bar(99, volume=5, date="d1")]
    assert drop_incomplete_bar(full) == full


class SmokeClient:
    """Fake india_client: ^NSEI history plus a few constituents, newest first."""

    def __init__(self, nifty50, stocks=4):
        self.nifty50 = nifty50
        self.stocks = stocks
        self.calls = 0

    def get_universe(self, name="nifty500"):
        return [f"S{i}" for i in range(self.stocks)]

    def get_historical_prices(self, symbol, days=365):
        self.calls += 1
        if symbol == "^NSEI":
            return {"symbol": symbol, "historical": self.nifty50}
        k = 1 + int(symbol[1:]) * 0.1
        rows = [
            dict(b, open=b["open"] * k, high=b["high"] * k, low=b["low"] * k, close=b["close"] * k)
            for b in self.nifty50
        ]
        return {"symbol": symbol, "historical": rows}

    def get_quote(self, symbols):
        return [{"symbol": "^NSEI", "price": self.nifty50[0]["close"]}]

    def get_api_stats(self):
        return {"api_calls_made": self.calls, "source": "fake"}


def test_end_to_end_smoke_with_composite(monkeypatch, tmp_path):
    nifty50 = market_history()
    client = SmokeClient(nifty50)
    monkeypatch.setattr("sys.argv", ["ftd_detector.py", "--output-dir", str(tmp_path)])
    ftd_detector.main(client=client)
    report, markdown = read_reports(tmp_path)
    assert report["market_state"]["combined_state"] == "FTD_CONFIRMED"
    assert report["midcap"]["current_price"] is not None
    assert "Nifty 50" in markdown

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)
