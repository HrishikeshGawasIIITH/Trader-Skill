"""Provenance block checks (self-contained)."""

import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import provenance_contract as pc  # noqa: E402


def block(**changes):
    value = pc.build_provenance(
        provider="india-client",
        endpoint="https://query1.finance.yahoo.com/v8/finance/chart",
        retrieved_at="2026-11-10T10:00:00+00:00",
        as_of="2026-11-10",
        run_id="run-1",
    )
    value.update(changes)
    return value


class ProvenanceTests(unittest.TestCase):
    def test_default_block_is_valid_and_uses_ist(self):
        b = block()
        self.assertEqual(pc.validate_provenance(b), [])
        self.assertEqual(b["timezone"], "Asia/Kolkata")
        for flag in ("adjusted", "point_in_time", "survivorship_free", "corporate_actions_handled"):
            self.assertIs(b[flag], False)

    def test_missing_and_invalid_fields_reported(self):
        self.assertTrue(pc.validate_provenance({}))
        self.assertTrue(pc.validate_provenance(block(as_of="2026-99-99")))
        self.assertTrue(pc.validate_provenance(block(retrieved_at="yesterday")))
        self.assertTrue(pc.validate_provenance(block(adjusted="no")))
        self.assertEqual(pc.validate_provenance("x"), ["data_provenance must be a mapping"])

    def test_build_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            pc.build_provenance(
                provider="p",
                endpoint="e",
                retrieved_at="2026-11-10T10:00:00+00:00",
                as_of="bad",
                run_id="r",
            )

    def test_handoff_accepts_fresh_and_rejects_stale(self):
        b = block()
        ok = pc.validate_handoff(
            b, run_id="run-1", evaluation="2026-11-10T12:00:00+00:00", max_age_days=3
        )
        self.assertEqual(ok["as_of"], "2026-11-10")
        with self.assertRaises(ValueError):
            pc.validate_handoff(
                b, run_id="run-1", evaluation="2026-11-30T12:00:00+00:00", max_age_days=3
            )
        with self.assertRaises(ValueError):
            pc.validate_handoff(
                b, run_id="other", evaluation="2026-11-10T12:00:00+00:00", max_age_days=3
            )

    def test_source_identity_strips_credentials_and_query(self):
        self.assertEqual(
            pc.safe_source_url("https://user:pw@example.com:8443/a/b?token=1#frag"),
            "https://example.com:8443/a/b",
        )

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)


if __name__ == "__main__":
    unittest.main()
