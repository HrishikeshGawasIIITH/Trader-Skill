"""Tests for the NSE earnings calendar scripts (fake client, no network).

Covers:
- NSEEarningsCalendar helper methods
- Date validation
- End-to-end run() and main() with a fake client
- Report generation (generate_report.py pure functions)
"""

import json
import sys
from unittest.mock import patch

import fetch_earnings_nse as fetcher
import pytest
from fetch_earnings_nse import NSEEarningsCalendar, validate_date
from generate_report import (
    calculate_summary_stats,
    generate_report,
    get_day_name,
    group_by_date,
    load_earnings_data,
)


class FakeClient:
    """Stands in for india_client.FMPClient."""

    universes = {
        "nifty50": ["TCS", "RELIANCE"],
        "midcap150": ["MPHASIS"],
        "smallcap250": ["TEGA"],
        "nifty500": ["TCS", "RELIANCE", "MPHASIS", "TEGA", "ITC"],
    }

    def __init__(self, calendar=None, fail=False):
        self.calendar = calendar if calendar is not None else [
            {"symbol": "TEGA", "date": "2026-11-12", "purpose": "Financial Results", "company": "Tega"},
            {"symbol": "TCS", "date": "2026-11-12", "purpose": "Financial Results", "company": "TCS"},
            {"symbol": "TCS", "date": "2026-11-12", "purpose": "Financial Results", "company": "TCS"},
            {"symbol": "ZZZ", "date": "2026-11-13", "purpose": "Financial Results", "company": "Zed"},
            {"symbol": "MPHASIS", "date": "2026-11-13", "purpose": "Financial Results", "company": "Mphasis"},
        ]
        self.fail = fail

    def get_earnings_calendar(self, start, end):
        if self.fail:
            raise RuntimeError("down")
        return list(self.calendar)

    def get_company_profiles(self, symbols):
        return {
            s: {"companyName": f"{s} Ltd", "industry": "Software", "sector": "Software"}
            for s in symbols
            if s != "ZZZ"
        }

    def get_universe(self, name):
        return list(self.universes[name])


@pytest.fixture
def pipeline():
    return NSEEarningsCalendar(client=FakeClient())


@pytest.fixture
def sample_earnings():
    return [
        {"symbol": "TCS", "companyName": "TCS Ltd", "date": "2026-11-12", "timing": "TAS",
         "index": "Nifty 50", "sector": "IT", "industry": "Software", "exchange": "NSE"},
        {"symbol": "MPHASIS", "companyName": "Mphasis", "date": "2026-11-13", "timing": "TAS",
         "index": "Midcap 150", "sector": "IT", "industry": "Software", "exchange": "NSE"},
        {"symbol": "TEGA", "companyName": "Tega", "date": "2026-11-13", "timing": "TAS",
         "index": "Smallcap 250", "sector": "Industrial", "industry": "Machinery", "exchange": "NSE"},
    ]


# -- normalize_timing --------------------------------------------------


class TestNormalizeTiming:
    def test_bmo_variants(self, pipeline):
        for value in ["bmo", "BMO", "pre-market", "Before Market Open"]:
            assert pipeline.normalize_timing(value) == "BMO"

    def test_amc_variants(self, pipeline):
        for value in ["amc", "AMC", "after-market", "After Market Close"]:
            assert pipeline.normalize_timing(value) == "AMC"

    def test_none_returns_tas(self, pipeline):
        assert pipeline.normalize_timing(None) == "TAS"

    def test_unknown_returns_tas(self, pipeline):
        assert pipeline.normalize_timing("unknown") == "TAS"
        assert pipeline.normalize_timing("") == "TAS"


# -- pipeline ----------------------------------------------------------


class TestPipeline:
    def test_fetch_failure_returns_none(self):
        p = NSEEarningsCalendar(client=FakeClient(fail=True))
        assert p.fetch_earnings_calendar("2026-11-12", "2026-11-13") is None

    def test_tier_map_prefers_largest_index(self, pipeline):
        tiers = pipeline.tier_map()
        assert tiers["TCS"] == "Nifty 50"
        assert tiers["MPHASIS"] == "Midcap 150"
        assert tiers["TEGA"] == "Smallcap 250"
        assert tiers["ITC"] == "Nifty 500"

    def test_filter_drops_outsiders_and_duplicates_and_enriches(self, pipeline):
        earnings = pipeline.fetch_earnings_calendar("2026-11-12", "2026-11-13")
        profiles = pipeline.fetch_company_profiles(["TCS", "TEGA", "MPHASIS"])
        rows = pipeline.filter_by_universe(earnings, profiles, pipeline.tier_map())
        assert sorted(r["symbol"] for r in rows) == ["MPHASIS", "TCS", "TEGA"]
        tcs = next(r for r in rows if r["symbol"] == "TCS")
        assert tcs["companyName"] == "TCS Ltd"
        assert tcs["index"] == "Nifty 50"
        assert tcs["exchange"] == "NSE"

    def test_universe_choice_limits_rows(self):
        p = NSEEarningsCalendar(client=FakeClient(), universe="nifty50")
        rows = fetcher.run("2026-11-12", "2026-11-13", "nifty50", client=FakeClient())
        assert [r["symbol"] for r in rows] == ["TCS"]
        assert p.universe == "nifty50"

    def test_run_sorts_by_date_then_index_tier(self):
        rows = fetcher.run("2026-11-12", "2026-11-13", "nifty500", client=FakeClient())
        assert [(r["date"], r["symbol"]) for r in rows] == [
            ("2026-11-12", "TCS"),
            ("2026-11-12", "TEGA"),
            ("2026-11-13", "MPHASIS"),
        ]
        assert all(r["timing"] == "TAS" for r in rows)

    def test_run_empty_calendar(self):
        assert fetcher.run("2026-11-12", "2026-11-13", "nifty500", client=FakeClient(calendar=[])) == []

    def test_run_failure_returns_none(self):
        assert fetcher.run("2026-11-12", "2026-11-13", "nifty500", client=FakeClient(fail=True)) is None

    def test_main_prints_json(self, capsys):
        with patch.object(fetcher, "FMPClient", FakeClient):
            fetcher.main(["2026-11-12", "2026-11-13"])
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 3

    def test_main_rejects_bad_date(self, capsys):
        with pytest.raises(SystemExit) as exc:
            fetcher.main(["2026-13-01", "2026-11-13"])
        assert exc.value.code == 1


class TestValidateDate:
    def test_valid_date(self):
        assert validate_date("2026-11-12") is True

    def test_invalid_format(self):
        assert validate_date("12-11-2026") is False

    def test_invalid_date(self):
        assert validate_date("2026-02-30") is False


# -- report generation helpers -----------------------------------------


class TestGroupByDate:
    def test_groups_correctly(self, sample_earnings):
        result = group_by_date(sample_earnings)
        assert len(result["2026-11-12"]["TAS"]) == 1
        assert len(result["2026-11-13"]["TAS"]) == 2

    def test_empty_input(self):
        assert group_by_date([]) == {}

    def test_null_and_unknown_timing_fall_back_to_tas(self):
        earnings = [
            {"date": "2026-07-13", "timing": None},
            {"date": "2026-07-13", "timing": "UNKNOWN"},
        ]
        assert group_by_date(earnings)["2026-07-13"]["TAS"] == earnings


class TestGetDayName:
    def test_known_date(self):
        result = get_day_name("2026-11-12")
        assert "Thursday" in result
        assert "November" in result


class TestCalculateSummaryStats:
    def test_stats(self, sample_earnings):
        stats = calculate_summary_stats(sample_earnings)
        assert stats["total"] == 3
        assert stats["large_cap"] == 1
        assert stats["mid_cap"] == 1
        assert stats["small_cap"] == 1
        assert stats["sectors"]["IT"] == 2
        assert stats["peak_count"] == 2
        assert stats["peak_date"] == "2026-11-13"

    def test_records_without_dates_have_no_peak(self):
        stats = calculate_summary_stats([{"symbol": "NODATE", "date": ""}])
        assert stats["peak_date"] is None
        assert stats["peak_count"] == 0


class TestGenerateReport:
    def test_report_contains_companies(self, sample_earnings):
        report = generate_report(sample_earnings)
        for symbol in ("TCS", "MPHASIS", "TEGA"):
            assert symbol in report

    def test_empty_earnings(self):
        assert "No results data available" in generate_report([])

    def test_report_has_sections(self, sample_earnings):
        report = generate_report(sample_earnings)
        assert "Executive Summary" in report
        assert "Key Observations" in report
        assert "Sector Distribution" in report
        assert "Nifty 50" in report

    def test_no_us_or_dollar_text(self, sample_earnings):
        report = generate_report(sample_earnings)
        assert "$" not in report
        assert "FMP" not in report
        assert " ET " not in report

    def test_empty_bmo_amc_blocks_are_skipped(self, sample_earnings):
        report = generate_report(sample_earnings)
        assert "Before Market Open" not in report
        assert "Time Not Announced" in report

    def test_null_company_and_sector_render_as_na(self):
        report = generate_report(
            [
                {
                    "symbol": "NULLS",
                    "companyName": None,
                    "sector": None,
                    "date": "2026-07-13",
                    "timing": "BMO",
                }
            ]
        )
        assert "NULLS" in report
        assert "N/A" in report


class TestLoadEarningsData:
    def test_skips_bracketed_progress_preamble(self, tmp_path):
        source = tmp_path / "earnings.json"
        source.write_text('[INFO] fetching page 1\n[{"symbol": "TCS"}]')
        assert load_earnings_data(str(source)) == [{"symbol": "TCS"}]

    def test_report_from_file(self, tmp_path, sample_earnings):
        source = tmp_path / "earnings.json"
        source.write_text(json.dumps(sample_earnings))
        assert "TCS" in generate_report(load_earnings_data(str(source)))
