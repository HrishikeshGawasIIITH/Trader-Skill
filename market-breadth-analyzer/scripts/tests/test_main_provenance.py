"""Real orchestration emits provenance from computed primary rows."""

import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import json
from datetime import datetime, timedelta
from unittest import mock

import market_breadth_analyzer as analyzer
import pytest


def run_main(output, rows, run_id=None):
    argv = ["market_breadth_analyzer.py", "--output-dir", str(output)]
    if run_id is not None:
        argv += ["--run-id", run_id]
    with (
        mock.patch.object(analyzer, "load_breadth", return_value=(rows, {}, {}, {})),
        mock.patch("sys.argv", argv),
    ):
        analyzer.main()
    report = next(p for p in output.glob("market_breadth_*.json") if "history" not in p.name)
    return json.loads(report.read_text())["data_provenance"]


def test_main_records_primary_date_and_run(tmp_path, make_rows):
    block = run_main(tmp_path, make_rows(25), "shared-run")
    assert block["run_id"] == "shared-run"
    assert block["as_of"] == "2025-01-25"
    assert datetime.fromisoformat(block["retrieved_at"]).utcoffset() == timedelta(0)
    assert block["provider"] == "india-client"
    assert block["timezone"] == "Asia/Kolkata"
    assert "primary timeseries" in block["scope"]
    for flag in ("adjusted", "point_in_time", "survivorship_free", "corporate_actions_handled"):
        assert block[flag] is False


@pytest.mark.parametrize("date", [None, "", "2025-99-99"])
def test_invalid_primary_date_writes_no_report(tmp_path, make_rows, date):
    rows = make_rows(25)
    rows[-1]["Date"] = date
    with pytest.raises(ValueError):
        run_main(tmp_path, rows, "shared-run")
    assert list(tmp_path.iterdir()) == []


def test_default_run_id_is_unique(tmp_path, make_rows):
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first = run_main(tmp_path / "first", make_rows(25))
    second = run_main(tmp_path / "second", make_rows(25))
    assert first["run_id"] and second["run_id"]
    assert first["run_id"] != second["run_id"]

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)
