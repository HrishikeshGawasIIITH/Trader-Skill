"""Additional coverage tests for the Stockbee Momentum Burst screener."""

import json
import sys
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import screen_momentum_burst as smb  # noqa: E402
from screen_momentum_burst import (  # noqa: E402
    ApiCallBudgetExceeded,
    Bar,
    BaseProfile,
    FMPClient,
    TriggerProfile,
)


def _args(**overrides):
    base = dict(
        as_of="2026-01-30",
        max_bar_age_sessions=0,
        min_price=50.0,
        min_volume=100_000,
        four_pct_threshold=4.0,
        dollar_threshold=0.90,
        nine_million_volume=9_000_000,
        max_prev_day_gain_for_range=2.0,
        min_base_days=3,
        max_base_days=20,
        max_base_width_pct=15.0,
        max_prior_avg_range_pct=5.0,
        narrow_prior_day_range_pct=3.0,
        recent_breakdown_lookback=5,
        breakdown_threshold_pct=4.0,
        max_risk_pct_to_stop=10.0,
        market_gate="allowed",
    )
    base.update(overrides)
    return Namespace(**base)


def _bar(d, o, h, low, c, v=200_000):
    return Bar(d, o, h, low, c, v)


def _flat_bars(n=30, close=100.0, volume=200_000):
    """Most-recent-first flat bars with distinct dates."""
    return [
        Bar(
            (date(2026, 1, 30) - timedelta(days=i)).isoformat(),
            close,
            close + 0.5,
            close - 0.5,
            close,
            volume,
        )
        for i in range(n)
    ]


class _FakeShared:
    """Stands in for india_client.FMPClient inside the adapter."""

    def __init__(self, **kw):
        self.max_api_calls = kw.get("max_api_calls")
        self.api_calls_made = 0
        self.rate_limit_reached = False
        self.hist_calls = 0

    def get_universe_rows(self, name):
        return [
            {"Symbol": "RELIANCE", "Company Name": "Reliance", "Industry": "Oil"},
            {"Symbol": "M&M", "Company Name": "Mahindra", "Industry": "Auto"},
            {"Symbol": "", "Company Name": "blank"},
        ]

    def get_trading_holidays(self):
        return ["2026-01-26"]

    def get_historical_prices(self, symbol, days=365):
        self.hist_calls += 1
        if symbol == "GONE":
            return None
        if symbol == "EMPTY":
            return {"symbol": symbol, "historical": []}
        return {"symbol": symbol, "historical": [{"date": "2026-01-30", "close": 10}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(smb.india_client, "FMPClient", _FakeShared)
    return FMPClient(max_api_calls=5)


def test_adapter_needs_no_key(client):
    assert client.max_api_calls == 5
    assert client.api_calls_made == 0


def test_budget_exception_is_the_client_exception():
    assert ApiCallBudgetExceeded is smb.india_client.ApiCallBudgetExceeded


def test_get_universe_rows_normalized_and_capped(client):
    rows = client.get_universe("nifty500", 10)
    assert [r["symbol"] for r in rows] == ["RELIANCE", "M&M"]
    assert [r["symbol"] for r in client.get_universe("nifty500", 1)] == ["RELIANCE"]


def test_get_trading_holidays_passthrough(client):
    assert client.get_trading_holidays() == ["2026-01-26"]


def test_get_historical_prices_cached(client):
    assert client.get_historical_prices("abc", days=30)[0]["close"] == 10
    client.get_historical_prices("ABC", days=30)
    assert client._client.hist_calls == 1


def test_get_historical_prices_empty_cached_failure_not_cached(client):
    assert client.get_historical_prices("EMPTY") == []
    client.get_historical_prices("EMPTY")
    assert client._client.hist_calls == 1
    assert client.get_historical_prices("GONE") == []
    client.get_historical_prices("GONE")
    assert client._client.hist_calls == 3


def test_get_api_stats(client):
    stats = client.get_api_stats()
    assert stats["budget_remaining"] == 5
    assert stats["source"] == "yahoo+nse"


# ------------------------------------------------------------ small helpers


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, ""),
        ("", ""),
        ("  nan ", ""),
        ("None", ""),
        ("null", ""),
        (" m&m ", "M&M"),
        (123, "123"),
    ],
)
def test_normalize_symbol(value, expected):
    assert smb.normalize_symbol(value) == expected


def test_numeric_coercions():
    assert smb.to_float("1.5") == 1.5
    assert smb.to_float(None, 7.0) == 7.0
    assert smb.to_float("", 3.0) == 3.0
    assert smb.to_float("abc", 2.0) == 2.0
    assert smb.to_int("12.9") == 12
    assert smb.to_int(None, 4) == 4
    assert smb.to_int("", 5) == 5
    assert smb.to_int("x", 6) == 6
    assert smb.safe_round("1.2349", 2) == 1.23
    assert smb.safe_round("bad") == 0.0


def test_normalize_bars_filters_sorts_limits():
    raw = [
        "junk",
        {"date": "2026-01-01", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
        {"timestamp": "2026-01-03", "open": 1, "high": 2, "low": 1, "adjClose": 1.5},
        {"open": 1, "high": 2, "low": 1, "close": 1},  # no date
        {"date": "2026-01-04", "open": 0, "high": 2, "low": 1, "close": 1},  # zero open
        {"date": "2026-01-05", "open": 1, "high": 1, "low": 2, "close": 1},  # high < low
        {"date": "2026-01-02", "open": 1, "high": 2, "low": 1, "close": 1.2, "volume": "5"},
    ]
    unplaceable, *bars = smb.normalize_bars(raw)
    assert unplaceable.date == ""  # retained for fail-closed analysis, never silently dropped
    assert [b.date for b in bars] == ["2026-01-03", "2026-01-02", "2026-01-01"]
    assert bars[0].close == 1.5
    assert bars[0].volume == 0
    assert bars[1].volume == 5
    assert [b.date for b in smb.normalize_bars(raw, limit=1)] == ["", "2026-01-03"]
    assert smb.normalize_bars(None) == []


def test_normalize_fmp_historical_response_shapes():
    f = smb.normalize_fmp_historical_response
    assert f(None, "A", 5) == []
    assert f([], "A", 5) == []
    rows = [
        {"symbol": "A", "date": "d1"},
        {"date": "d2"},
        {"symbol": "B", "date": "d3"},
        "junk",
    ]
    assert f(rows, "a", 5) == [{"date": "d1"}, {"date": "d2"}]
    assert f(rows, "a", 1) == [{"date": "d1"}]
    assert f({"historical": [1, 2, 3]}, "A", 2) == [1, 2]
    multi = {
        "historicalStockList": [
            {"symbol": "X", "historical": [{"d": 1}]},
            {"symbol": "A", "historical": [{"d": 2}, {"d": 3}]},
            {"symbol": "C", "historical": None},
        ]
    }
    assert f(multi, "A", 5) == [{"d": 2}, {"d": 3}]
    assert f(multi, "C", 5) == []
    assert f(multi, "Z", 5) == []
    assert f({"other": 1}, "A", 5) == []
    assert f("str", "A", 5) == []


def test_read_universe_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="Universe file not found"):
        smb.read_universe_file(str(tmp_path / "nope.csv"))


def test_read_universe_file_json_shapes(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(["aapl", "AAPL", "msft", None]), encoding="utf-8")
    assert smb.read_universe_file(str(p)) == ["AAPL", "MSFT"]

    p.write_text(
        json.dumps({"symbols": [{"symbol": "nvda"}, {"ticker": "amd"}, "tsla"]}),
        encoding="utf-8",
    )
    assert smb.read_universe_file(str(p)) == ["AMD", "NVDA", "TSLA"]

    p.write_text(json.dumps({"tickers": ["x"]}), encoding="utf-8")
    assert smb.read_universe_file(str(p)) == ["X"]

    p.write_text(json.dumps({"nothing": 1}), encoding="utf-8")
    assert smb.read_universe_file(str(p)) == []

    p.write_text(json.dumps("scalar"), encoding="utf-8")
    assert smb.read_universe_file(str(p)) == []


def test_read_universe_file_csv_variants(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Ticker,x\nm&m,1\namd,2\n", encoding="utf-8")
    assert smb.read_universe_file(str(p)) == ["AMD", "M&M"]

    p.write_text("name\nfoo\nbar\n", encoding="utf-8")  # falls back to first column
    assert smb.read_universe_file(str(p)) == ["BAR", "FOO"]


def test_read_universe_file_empty_csv_falls_to_text(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("", encoding="utf-8")
    assert smb.read_universe_file(str(p)) == []


def test_read_universe_file_plain_text(tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("# comment\naapl, Apple\n\n msft \naapl\n", encoding="utf-8")
    assert smb.read_universe_file(str(p)) == ["AAPL", "MSFT"]


def _row(d, c=10.0):
    return {"date": d, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000}


def test_read_prices_json_shapes(tmp_path):
    p = tmp_path / "p.json"

    p.write_text(json.dumps({"symbols": {"aapl": [_row("2026-01-02")]}}), encoding="utf-8")
    assert list(smb.read_prices_json(str(p))) == ["AAPL"]

    p.write_text(
        json.dumps({"m&m": {"historical": [_row("2026-01-02")]}, "bad": 5, "empty": []}),
        encoding="utf-8",
    )
    assert list(smb.read_prices_json(str(p))) == ["M&M"]

    p.write_text(
        json.dumps(
            [
                {"symbol": "a", "historical": [_row("2026-01-02")]},
                {"ticker": "b", "bars": [_row("2026-01-02")]},
                {"symbol": "c", "prices": [_row("2026-01-02")]},
                {"symbol": "d", "historical": "nope"},
                {"historical": [_row("2026-01-02")]},
                "junk",
            ]
        ),
        encoding="utf-8",
    )
    assert sorted(smb.read_prices_json(str(p))) == ["A", "B", "C"]

    p.write_text(json.dumps("scalar"), encoding="utf-8")
    assert smb.read_prices_json(str(p)) == {}


def test_pct_change_and_close_location():
    assert smb.pct_change(110, 100) == pytest.approx(10.0)
    assert smb.pct_change(110, 0) == 0.0
    assert smb.average([]) == 0.0
    assert smb.average([1, 2, 3]) == 2.0
    assert smb.close_location_pct(_bar("d", 1, 10, 0, 7.5)) == 75.0
    assert smb.close_location_pct(_bar("d", 5, 5, 5, 5)) == 50.0


def test_up_streak_before_trigger():
    # idx0 = trigger, idx1..: closes strictly descending in age => each step is an up close
    closes = [120, 110, 108, 106, 104, 102, 100, 101, 99]
    bars = [_bar(f"d{i}", c, c + 1, c - 1, c) for i, c in enumerate(closes)]
    assert smb.up_streak_before_trigger(bars) == 5
    assert smb.up_streak_before_trigger(bars, max_days=2) == 2
    flat = _flat_bars(10)
    assert smb.up_streak_before_trigger(flat) == 0


def test_up_streak_breaks_on_first_down():
    closes = [120, 110, 108, 109, 104]
    bars = [_bar(f"d{i}", c, c + 1, c - 1, c) for i, c in enumerate(closes)]
    assert smb.up_streak_before_trigger(bars) == 1


def test_has_recent_breakdown():
    closes = [100, 100, 95, 100, 100, 100, 100, 100]
    bars = [_bar(f"d{i}", c, c + 1, c - 1, c) for i, c in enumerate(closes)]
    # idx2 close 95 vs idx3 100 => -5% within lookback
    assert smb.has_recent_breakdown(bars) is True
    assert smb.has_recent_breakdown(bars, threshold_pct=-6.0) is False
    assert smb.has_recent_breakdown(bars, lookback_days=0) is False
    quiet = _flat_bars(10)
    assert smb.has_recent_breakdown(quiet) is False


# ------------------------------------------------------------ base profile


def test_detect_base_profile_insufficient_bars():
    bp = smb.detect_base_profile(_flat_bars(4), 3, 20, 15.0, 5.0)
    assert bp == BaseProfile(0, 0.0, 0.0, False)


def test_detect_base_profile_picks_longest_window_and_dry_up():
    bars = _flat_bars(30)
    # Trigger bar then a quiet base with low volume; older volume is higher.
    bars = [
        Bar(b.date, b.open, b.high, b.low, b.close, 50_000 if 1 <= i <= 6 else 200_000)
        for i, b in enumerate(bars)
    ]
    bp = smb.detect_base_profile(bars, 3, 6, 15.0, 5.0)
    assert bp.prior_base_days == 6
    assert bp.base_width_pct == pytest.approx(1.0)
    assert bp.avg_prior_range_pct == pytest.approx(1.0)
    assert bp.volume_dry_up is True


def test_detect_base_profile_no_older_volume_means_no_dry_up():
    bars = _flat_bars(6)
    bp = smb.detect_base_profile(bars, 3, 5, 15.0, 5.0)
    assert bp.prior_base_days == 5
    assert bp.volume_dry_up is False  # no older window available


def test_detect_base_profile_fallback_when_nothing_qualifies():
    bars = [Bar(f"d{i}", 100, 130, 70, 100, 1000) for i in range(30)]
    bp = smb.detect_base_profile(bars, 3, 20, 15.0, 5.0)
    assert bp.prior_base_days == 0
    assert bp.base_width_pct == pytest.approx(60.0)
    assert bp.avg_prior_range_pct == pytest.approx(60.0)
    assert bp.volume_dry_up is False


def test_detect_base_profile_skips_nonpositive_reference_close():
    bars = _flat_bars(8)
    bars[1] = Bar(bars[1].date, 100, 101, 99, 0.0, 1000)
    # Pins current behavior: the window loop skips the bad reference close, but the
    # fallback path divides by it. Unreachable via normalize_bars (drops close <= 0).
    with pytest.raises(ZeroDivisionError):
        smb.detect_base_profile(bars, 3, 5, 15.0, 5.0)


# ---------------------------------------------------------------- triggers


def _trigger_bars():
    bars = _flat_bars(25)
    bars[0] = Bar(bars[0].date, 100.0, 105.0, 99.5, 105.0, 500_000)
    return bars


def test_detect_triggers_all_tags_and_primary_order():
    bars = _trigger_bars()
    bars[0] = Bar(bars[0].date, 100.0, 105.0, 99.5, 105.0, 10_000_000)
    p = smb.detect_triggers(bars, _args())
    assert p.trigger_tags == ["4pct_breakout", "dollar_breakout", "range_expansion", "9m_volume"]
    assert p.primary_trigger == "4pct_breakout"
    assert p.day_gain_pct == pytest.approx(5.0)
    assert p.dollar_gain == pytest.approx(5.0)
    assert p.current_range_dollars == pytest.approx(5.5)
    assert p.close_location_pct == pytest.approx(100 * 5.5 / 5.5)
    assert p.volume_ratio_1d == pytest.approx(50.0)
    assert p.volume_ratio_20d == pytest.approx(50.0)


def test_detect_triggers_dollar_only_when_volume_not_expanded():
    bars = _flat_bars(25)
    bars[0] = Bar(bars[0].date, 100.0, 101.5, 99.9, 101.0, 200_000)
    bars[1] = Bar(bars[1].date, 100.0, 100.5, 99.5, 100.0, 200_000)
    p = smb.detect_triggers(bars, _args())
    assert p.trigger_tags == ["dollar_breakout"]
    assert p.primary_trigger == "dollar_breakout"


def test_detect_triggers_none_and_zero_prev_volume():
    bars = _flat_bars(25)
    bars[1] = Bar(bars[1].date, 100, 100.5, 99.5, 100, 0)
    p = smb.detect_triggers(bars, _args())
    assert p.trigger_tags == []
    assert p.primary_trigger == "none"
    assert p.volume_ratio_1d == 0.0


def test_detect_triggers_9m_only_is_not_primary_executable():
    bars = _flat_bars(25, volume=200_000)
    bars[0] = Bar(bars[0].date, 100, 100.4, 99.6, 100, 9_500_000)
    p = smb.detect_triggers(bars, _args())
    assert p.trigger_tags == ["9m_volume"]
    assert p.primary_trigger == "9m_volume"


def test_detect_triggers_range_expansion_blocked_by_prev_day_gain():
    bars = _flat_bars(25)
    bars[0] = Bar(bars[0].date, 100, 103, 99, 100.5, 400_000)
    assert "range_expansion" in smb.detect_triggers(bars, _args()).trigger_tags
    bars[1] = Bar(bars[1].date, 100, 100.5, 99.5, 100, 200_000)
    bars[2] = Bar(bars[2].date, 90, 91, 89, 90, 200_000)  # prev day gained 11%
    tags = smb.detect_triggers(bars, _args()).trigger_tags
    assert "range_expansion" not in tags


# ------------------------------------------------------------ score pieces


def _profile(**kw):
    base = dict(
        trigger_tags=[],
        primary_trigger="none",
        day_gain_pct=0.0,
        dollar_gain=0.0,
        current_range_pct=0.0,
        current_range_dollars=0.0,
        volume_ratio_1d=0.0,
        volume_ratio_20d=0.0,
        close_location_pct=50.0,
        prev_day_gain_pct=0.0,
    )
    base.update(kw)
    return TriggerProfile(**base)


def test_trigger_score_components_and_cap():
    assert smb.trigger_score(_profile()) == 0
    assert smb.trigger_score(_profile(trigger_tags=["4pct_breakout"], day_gain_pct=5)) == 14
    assert smb.trigger_score(_profile(trigger_tags=["4pct_breakout"], day_gain_pct=7)) == 17
    assert smb.trigger_score(_profile(trigger_tags=["range_expansion"])) == 10
    assert smb.trigger_score(_profile(trigger_tags=["dollar_breakout"])) == 8
    assert smb.trigger_score(_profile(trigger_tags=["9m_volume"])) == 2
    everything = ["4pct_breakout", "range_expansion", "dollar_breakout", "9m_volume"]
    assert smb.trigger_score(_profile(trigger_tags=everything, day_gain_pct=9)) == 20


@pytest.mark.parametrize(
    "r1,r20,expected",
    [(0.5, 0.2, 0), (1.0, 0, 6), (0, 1.5, 9), (2.0, 0, 12), (1.0, 3.0, 15), (3.0, 0, 15)],
)
def test_volume_score_tiers(r1, r20, expected):
    assert smb.volume_score(_profile(volume_ratio_1d=r1, volume_ratio_20d=r20)) == expected


@pytest.mark.parametrize(
    "loc,expected",
    [(95, 10), (90, 10), (85, 9), (75, 7), (65, 5), (55, 3), (49.9, 0)],
)
def test_close_quality_score_tiers(loc, expected):
    assert smb.close_quality_score(loc) == expected


@pytest.mark.parametrize(
    "risk,expected",
    [(-1, 0), (0, 0), (2.5, 15), (3, 12), (4.0, 12), (5, 8), (7, 5), (9, 2), (10.5, 0)],
)
def test_risk_distance_score_tiers(risk, expected):
    assert smb.risk_distance_score(risk) == expected


def test_setup_score_tiers():
    narrow_prev = _bar("d", 100, 101, 100, 100.5)  # range 1% <= 3%
    wide_red_prev = _bar("d", 100, 106, 99, 99.5)  # range ~6.5%, red
    wide_green_prev = _bar("d", 100, 106, 99, 104)
    a = _args()
    assert smb.setup_score(BaseProfile(10, 7.0, 2.0, True), narrow_prev, a) == 10 + 7 + 5 + 3
    assert smb.setup_score(BaseProfile(5, 10.0, 2.0, False), wide_red_prev, a) == 8 + 5 + 4
    assert smb.setup_score(BaseProfile(3, 14.0, 2.0, False), wide_green_prev, a) == 6 + 3
    assert smb.setup_score(BaseProfile(1, 20.0, 2.0, False), wide_green_prev, a) == 3
    assert (
        smb.setup_score(BaseProfile(0, 0.0, 0.0, False), wide_green_prev, a) == 5
    )  # zero width scores 5
    # Cap at 25 can't be exceeded by the parts; verify exact max.
    assert smb.setup_score(BaseProfile(20, 1.0, 1.0, True), narrow_prev, a) == 25


def test_setup_score_zero_close_prev_bar():
    prev = Bar("d", 1, 2, 1, 0.0, 10)
    # zero width +5, prev_range_pct falls back to 0 -> narrow prior day +5
    assert smb.setup_score(BaseProfile(0, 0.0, 0.0, False), prev, _args()) == 10


def test_failure_filter_score_all_penalties_and_floor():
    a = _args()
    base_ok = BaseProfile(5, 5.0, 2.0, False)
    score, reasons = smb.failure_filter_score(_profile(close_location_pct=80), base_ok, 0, False, a)
    assert (score, reasons) == (10, [])
    wide = BaseProfile(0, 30.0, 9.0, False)
    score, reasons = smb.failure_filter_score(_profile(close_location_pct=10), wide, 4, True, a)
    assert reasons == [
        "prior_3day_runup",
        "recent_4pct_breakdown",
        "wide_prior_base",
        "weak_close_location",
    ]
    assert score == 0


def test_market_gate_rating_state_mapping():
    assert [smb.market_gate_score(g) for g in ("allowed", "neutral", "restrictive")] == [5, 3, 0]
    assert smb.market_gate_score("bogus") == 0
    ratings = {95: "A", 90: "A", 85: "A-", 80: "A-", 75: "B", 70: "B", 60: "Watch", 55: "Watch"}
    for score, rating in ratings.items():
        assert smb.score_to_rating(score) == rating
    assert smb.score_to_rating(54) == "Reject"

    assert smb.score_to_state(99, "allowed", True) == "REJECTED"
    assert smb.score_to_state(85, "restrictive", False) == "MANUAL_REVIEW_ONLY"
    assert smb.score_to_state(60, "restrictive", False) == "WATCH_ONLY"
    assert smb.score_to_state(85, "allowed", False) == "ACTIONABLE_DAY1"
    assert smb.score_to_state(75, "neutral", False) == "MANUAL_REVIEW"
    assert smb.score_to_state(55, "neutral", False) == "WATCH_ONLY"
    assert smb.score_to_state(54, "neutral", False) == "REJECTED"


def test_downstream_action_for_each_state():
    texts = {
        s: smb.downstream_action(s, "x")
        for s in [
            "ACTIONABLE_DAY1",
            "MANUAL_REVIEW",
            "MANUAL_REVIEW_ONLY",
            "WATCH_ONLY",
            "REJECTED",
        ]
    }
    assert texts["ACTIONABLE_DAY1"].startswith("Send to technical-analyst")
    assert texts["MANUAL_REVIEW"].startswith("Manual chart review only")
    assert "restrictive" in texts["MANUAL_REVIEW_ONLY"]
    assert texts["WATCH_ONLY"].startswith("Watchlist")
    assert texts["REJECTED"].startswith("Do not trade")
    assert len(set(texts.values())) == 5


# ----------------------------------------------------------- analyze_symbol


def test_analyze_symbol_insufficient_history_skeleton():
    res = smb.analyze_symbol("x.y", _flat_bars(10), _args())
    assert res == {
        "date": "2026-01-30",
        "latest_bar_date": "2026-01-30",
        "expected_session": "2026-01-30",
        "max_bar_age_sessions": 0,
        "bar_age_sessions": 0,
        "downstream_action": smb.downstream_action("REJECTED", "Reject"),
        "symbol": "X.Y",
        "state": "REJECTED",
        "rating": "Reject",
        "setup_score": 0,
        "reject_reasons": ["insufficient_history"],
    }


def test_analyze_symbol_price_and_volume_floors():
    bars = _flat_bars(30, close=3.0, volume=50_000)
    res = smb.analyze_symbol("pen", bars, _args())
    assert res["state"] == "REJECTED"
    assert res["rating"] == "Reject"
    assert res["setup_score"] == 0
    assert res["raw_setup_score"] > 0
    assert res["reject_reasons"][:2] == ["below_min_price", "below_min_volume"]
    assert "no_momentum_burst_trigger" in res["reject_reasons"]


def test_analyze_symbol_9m_volume_alone_is_not_executable():
    bars = _flat_bars(30)
    bars[0] = Bar(bars[0].date, 100, 100.4, 99.6, 100, 9_500_000)
    res = smb.analyze_symbol("VOL", bars, _args())
    assert res["trigger_tags"] == ["9m_volume"]
    assert res["reject_reasons"] == ["no_momentum_burst_trigger"]
    assert res["state"] == "REJECTED"


def test_analyze_symbol_invalid_stop_reference():
    bars = _flat_bars(30)
    bars[0] = Bar(bars[0].date, 100, 106, 105, 105, 500_000)  # close == low
    res = smb.analyze_symbol("STOP", bars, _args())
    assert "invalid_stop_reference" in res["reject_reasons"]
    assert res["risk_pct_to_stop"] == 0.0
    assert res["components"]["risk_distance"] == 0
    assert res["state"] == "REJECTED"


def test_analyze_symbol_full_payload_values():
    bars = _flat_bars(30)
    bars[0] = Bar(bars[0].date, 100.0, 105.0, 100.0, 105.0, 500_000)
    res = smb.analyze_symbol("pay", bars, _args())
    assert res["symbol"] == "PAY"
    assert res["date"] == bars[0].date
    assert res["reject_reasons"] == []
    assert res["day_gain_pct"] == 5.0
    assert res["prev_close"] == 100.0
    assert res["close_location_pct"] == 100.0
    assert res["risk_pct_to_stop"] == pytest.approx(4.76)
    assert res["entry_reference"] == 105.0
    assert res["stop_reference"] == 100.0
    assert res["volume_ratio_1d"] == 2.5
    assert res["exit_template"] == "3_to_5_day_or_abnormal_profit_protection"
    assert res["components"]["market_gate"] == 5
    assert res["setup_score"] == res["raw_setup_score"] == sum(res["components"].values())
    assert res["downstream_action"] == smb.downstream_action(res["state"], res["rating"])


def test_analyze_symbol_restrictive_gate_goes_manual_review_only():
    bars = _flat_bars(30)
    bars[0] = Bar(bars[0].date, 100.0, 105.0, 100.0, 105.0, 500_000)
    allowed = smb.analyze_symbol("G", bars, _args(market_gate="allowed"))
    restrictive = smb.analyze_symbol("G", bars, _args(market_gate="restrictive"))
    assert allowed["components"]["market_gate"] == 5
    assert restrictive["components"]["market_gate"] == 0
    assert allowed["raw_setup_score"] - restrictive["raw_setup_score"] == 5
    if restrictive["raw_setup_score"] >= 70:
        assert restrictive["state"] == "MANUAL_REVIEW_ONLY"


def test_analyze_symbol_soft_failure_tags_prior_runup():
    closes = [105, 100, 98, 96, 94, 92] + [90] * 24
    bars = [
        Bar(
            (date(2026, 1, 30) - timedelta(days=i)).isoformat(),
            c,
            c + 0.5,
            c - 0.5,
            c,
            200_000 if i else 500_000,
        )
        for i, c in enumerate(closes)
    ]
    res = smb.analyze_symbol("RUN", bars, _args())
    assert res["prior_up_streak"] == 5
    assert "prior_3day_runup" in res["soft_failure_tags"]


# ------------------------------------------------------------- sort/report


def test_sort_results_orders_by_state_then_score():
    rows = [
        {"symbol": "R", "state": "REJECTED", "setup_score": 0},
        {"symbol": "W", "state": "WATCH_ONLY", "setup_score": 60},
        {"symbol": "A2", "state": "ACTIONABLE_DAY1", "setup_score": 82},
        {"symbol": "A1", "state": "ACTIONABLE_DAY1", "setup_score": 90},
        {"symbol": "U", "state": "???", "setup_score": 99},
        {"symbol": "M", "state": "MANUAL_REVIEW", "setup_score": 75},
        {"symbol": "O", "state": "MANUAL_REVIEW_ONLY", "setup_score": 71},
    ]
    assert [r["symbol"] for r in smb.sort_results(rows)] == ["A1", "A2", "M", "O", "W", "R", "U"]


def test_generate_json_report_roundtrip(tmp_path):
    out = tmp_path / "r.json"
    smb.generate_json_report([{"symbol": "A"}], {"k": "v"}, str(out))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {
        "schema_version": "1.0",
        "skill": "stockbee-momentum-burst-screener",
        "warnings": [],
        "metadata": {"k": "v"},
        "candidates": [{"symbol": "A"}],
    }


def test_format_candidate_md_full_row():
    bars = _flat_bars(30)
    bars[0] = Bar(bars[0].date, 100.0, 105.0, 100.0, 105.0, 500_000)
    row = smb.analyze_symbol("MDX", bars, _args())
    md = smb.format_candidate_md(row)
    assert md.startswith(f"### MDX — {row['rating']} / {row['setup_score']}")
    assert "- Volume: 500,000 (2.5x previous day" in md
    assert "Reject reasons: none" in md
    assert "4pct_breakout" in md
    assert "Entry / stop reference: 105.0 / 100.0 (4.76% risk to stop)" in md


def _meta():
    return {
        "generated_at": "2026-06-20 00:00:00",
        "input_mode": "symbols",
        "symbols_processed": 3,
        "market_gate": "neutral",
    }


def test_generate_markdown_report_counts_top_and_rejected(tmp_path):
    full = lambda s, st, sc: {  # noqa: E731
        "symbol": s,
        "state": st,
        "setup_score": sc,
        "rating": "B",
        "volume": 10,
    }
    rows = [
        full("AAA", "ACTIONABLE_DAY1", 85),
        full("BBB", "WATCH_ONLY", 60),
        full("CCC", "REJECTED", 0),
    ]
    out = tmp_path / "r.md"
    smb.generate_markdown_report(rows, _meta(), str(out), top=1, include_rejected=False)
    text = out.read_text(encoding="utf-8")
    assert "- Non-rejected candidates: 1" in text
    assert "- Rejected candidates: 1" in text
    assert "| ACTIONABLE_DAY1 | 1 |" in text
    assert "| MANUAL_REVIEW | 0 |" in text
    assert "### AAA" in text
    assert "### BBB" not in text
    assert "## Rejected" not in text

    smb.generate_markdown_report(rows, _meta(), str(out), top=10, include_rejected=True)
    text = out.read_text(encoding="utf-8")
    assert "### BBB" in text
    assert "## Rejected" in text
    assert "### CCC" in text


def test_generate_markdown_report_no_candidates(tmp_path):
    out = tmp_path / "r.md"
    smb.generate_markdown_report([], _meta(), str(out), top=5, include_rejected=True)
    text = out.read_text(encoding="utf-8")
    assert "No non-rejected candidates found." in text
    assert "## Rejected" not in text


# ------------------------------------------------------- args / collection


def test_parse_arguments_defaults_and_overrides(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog"])
    a = smb.parse_arguments()
    assert a.market_gate == "neutral"
    assert a.max_symbols == 500
    assert a.history_days == 80
    assert a.output_dir == "reports/"
    assert a.symbols == []
    assert a.universe_name is None

    monkeypatch.setattr(
        sys, "argv", ["prog", "--symbols", "a", "b", "--market-gate", "restrictive", "--top", "3"]
    )
    a = smb.parse_arguments()
    assert a.symbols == ["a", "b"]
    assert a.market_gate == "restrictive"
    assert a.top == 3


def test_build_symbol_list_merges_dedups_and_caps(tmp_path):
    uni = tmp_path / "u.txt"
    uni.write_text("msft\nzzz\n", encoding="utf-8")
    a = Namespace(symbols=["aapl", "AAPL", "", "nan"], universe_file=str(uni), max_symbols=3)
    assert smb.build_symbol_list(a) == ["AAPL", "MSFT", "ZZZ"]
    a.max_symbols = 2
    assert smb.build_symbol_list(a) == ["AAPL", "MSFT"]
    a.universe_file = None
    assert smb.build_symbol_list(a) == ["AAPL"]


def _col_args(**kw):
    base = dict(
        prices_json=None,
        symbols=[],
        universe_file=None,
        max_symbols=10,
        max_api_calls=50,
        universe_name=None,
        as_of=None,
        min_price=50.0,
        min_volume=100_000,
        history_days=30,
    )
    base.update(kw)
    return Namespace(**base)


def _price_rows(n=30, c=100.0):
    return [
        {
            "date": (date(2026, 3, 30) - timedelta(days=i)).isoformat(),
            "open": c,
            "high": c + 1,
            "low": c - 1,
            "close": c,
            "volume": 1000,
        }
        for i in range(n)
    ]


def test_collect_price_data_offline_filters_by_symbols(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"AAA": _price_rows(), "BBB": _price_rows()}), encoding="utf-8")
    data, stats = smb.collect_price_data(_col_args(prices_json=str(p), symbols=["bbb"]))
    assert stats is None
    assert list(data) == ["BBB"]
    data, _ = smb.collect_price_data(_col_args(prices_json=str(p)))
    assert sorted(data) == ["AAA", "BBB"]


def test_collect_price_data_empty_universe_raises(monkeypatch):
    fake = _FakeClient({}, universe=[])
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    with pytest.raises(ValueError, match="No symbols to process"):
        smb.collect_price_data(_col_args())


class _FakeClient:
    def __init__(self, histories, universe=None, budget_after=None):
        self.histories = histories
        self.universe = universe or []
        self.budget_after = budget_after
        self.calls = []

    def get_universe(self, name, max_symbols):
        self.universe_args = (name, max_symbols)
        return self.universe

    def get_trading_holidays(self):
        return []

    def get_historical_prices(self, symbol, days=80):
        self.calls.append((symbol, days))
        if self.budget_after is not None and len(self.calls) > self.budget_after:
            raise ApiCallBudgetExceeded("done")
        return self.histories.get(symbol, [])

    def get_api_stats(self):
        return {"api_calls_made": len(self.calls)}


def test_collect_price_data_symbols_via_client(monkeypatch, capsys):
    fake = _FakeClient({"AAA": _price_rows(), "BBB": []})
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    data, stats = smb.collect_price_data(_col_args(symbols=["aaa", "bbb"]))
    assert list(data) == ["AAA"]
    assert stats == {"api_calls_made": 2}
    assert fake.calls == [("AAA", 40), ("BBB", 40)]
    assert "Fetching history: 2/2" in capsys.readouterr().out


def test_collect_price_data_default_universe_is_nifty500(monkeypatch):
    fake = _FakeClient({"U1": _price_rows()}, universe=[{"symbol": "U1"}])
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    data, _ = smb.collect_price_data(_col_args(max_symbols=7))
    assert list(data) == ["U1"]
    assert fake.universe_args == ("nifty500", 7)


def test_collect_price_data_named_universe(monkeypatch):
    fake = _FakeClient({"U1": _price_rows()}, universe=[{"symbol": "U1"}])
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    smb.collect_price_data(_col_args(universe_name="midcap150"))
    assert fake.universe_args[0] == "midcap150"


def test_collect_price_data_budget_exhaustion_keeps_partial(monkeypatch, capsys):
    fake = _FakeClient(
        {"AAA": _price_rows(), "BBB": _price_rows(), "CCC": _price_rows()}, budget_after=1
    )
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    data, _ = smb.collect_price_data(_col_args(symbols=["AAA", "BBB", "CCC"]))
    assert list(data) == ["AAA"]
    assert "API budget exhausted at BBB" in capsys.readouterr().out


def test_collect_price_data_progress_every_25(monkeypatch, capsys):
    syms = [f"S{i:02d}" for i in range(26)]
    fake = _FakeClient({})
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    data, _ = smb.collect_price_data(_col_args(symbols=syms, max_symbols=100))
    assert data == {}
    out = capsys.readouterr().out
    assert "Fetching history: 25/26" in out
    assert "Fetching history: 26/26" in out


# --------------------------------------------------------------------- main


def _breakout_rows():
    rows = _price_rows(30)
    # Most-recent-first dates; make trigger on latest date.
    rows[0] = {
        "date": rows[0]["date"],
        "open": 100.0,
        "high": 105.0,
        "low": 100.0,
        "close": 105.0,
        "volume": 500_000,
    }
    for r in rows[1:]:
        r["volume"] = 200_000
    return rows


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["prog", "--as-of", "2026-03-30", *argv])
    smb.main()


def test_main_offline_writes_reports_and_prints_top(monkeypatch, tmp_path, capsys):
    prices = tmp_path / "p.json"
    prices.write_text(
        json.dumps({"WIN": _breakout_rows(), "SHORT": _price_rows(5)}), encoding="utf-8"
    )
    out = tmp_path / "out" / "nested"
    _run_main(
        monkeypatch,
        [
            "--prices-json",
            str(prices),
            "--output-dir",
            str(out),
            "--market-gate",
            "allowed",
            "--include-rejected",
        ],
    )
    stdout = capsys.readouterr().out
    jsons = list(out.glob("stockbee_momentum_burst_*.json"))
    mds = list(out.glob("stockbee_momentum_burst_*.md"))
    assert len(jsons) == 1 and len(mds) == 1
    payload = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert payload["metadata"]["input_mode"] == "prices_json"
    assert payload["metadata"]["symbols_processed"] == 2
    assert payload["metadata"]["api_stats"] is None
    assert payload["metadata"]["thresholds"]["min_price"] == 50.0
    assert [c["symbol"] for c in payload["candidates"]] == ["WIN", "SHORT"]
    assert payload["candidates"][0]["state"] == "ACTIONABLE_DAY1"
    assert payload["candidates"][1]["reject_reasons"] == ["insufficient_history"]
    md = mds[0].read_text(encoding="utf-8")
    assert "## Rejected" in md and "### SHORT" in md
    assert "Top candidates:" in stdout
    assert "1. WIN" in stdout
    assert "ACTIONABLE_DAY1" in stdout
    assert "Trigger: 4pct_breakout" in stdout


def test_main_all_rejected_prints_no_top_section(monkeypatch, tmp_path, capsys):
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps({"SHORT": _price_rows(5)}), encoding="utf-8")
    _run_main(monkeypatch, ["--prices-json", str(prices), "--output-dir", str(tmp_path / "o")])
    stdout = capsys.readouterr().out
    assert "Screening complete" in stdout
    assert "Top candidates:" not in stdout


def test_main_no_price_data_exits_zero(monkeypatch, tmp_path, capsys):
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["--prices-json", str(prices), "--output-dir", str(tmp_path)])
    assert exc.value.code == 0
    assert "No price data found" in capsys.readouterr().out
    assert list(tmp_path.glob("stockbee_momentum_burst_*")) == []


def test_main_missing_prices_file_exits_one(monkeypatch, tmp_path):
    # read_prices_json uses Path.read_text -> FileNotFoundError is mapped to exit 1.
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["--prices-json", str(tmp_path / "missing.json")])
    assert exc.value.code == 1


def test_main_symbols_mode_records_api_stats(monkeypatch, tmp_path):
    fake = _FakeClient({"AAA": _breakout_rows()})
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    _run_main(monkeypatch, ["--symbols", "AAA", "--output-dir", str(tmp_path)])
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["metadata"]["input_mode"] == "symbols"
    assert payload["metadata"]["api_stats"] == {"api_calls_made": 1}
    assert payload["metadata"]["market_gate"] == "neutral"


def test_main_universe_mode_label(monkeypatch, tmp_path):
    fake = _FakeClient({"U1": _breakout_rows()}, universe=[{"symbol": "U1"}])
    monkeypatch.setattr(smb, "FMPClient", lambda **kw: fake)
    _run_main(monkeypatch, ["--universe-name", "nifty50", "--output-dir", str(tmp_path)])
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["metadata"]["input_mode"] == "universe"
