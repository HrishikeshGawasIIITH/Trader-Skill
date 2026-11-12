import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_DIR / "SKILL.md"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

EXPECTED_RESOURCES = (
    "references/technical_analysis_framework.md",
    "assets/analysis_template.md",
    "references/contrarian-confirmation-checklist.md",
    "scripts/check_weekly_price_action.py",
)


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


class FakeClient:
    """Stands in for india_client.FMPClient. Returns daily bars newest first."""

    def __init__(self, days=400, rising=True):
        self.days = days
        self.rising = rising

    def get_historical_prices(self, symbol, days=365):
        end = date(2026, 11, 10)
        rows = []
        d = end - timedelta(days=self.days)
        px = 100.0
        while d <= end:
            if d.weekday() < 5:
                px += 0.3 if self.rising else -0.1
                rows.append(
                    {
                        "date": d.isoformat(),
                        "open": px - 0.2,
                        "high": px + 1.0,
                        "low": px - 1.0,
                        "close": px,
                        "adjClose": px,
                        "volume": 1000,
                    }
                )
            d += timedelta(days=1)
        return {"symbol": symbol, "historical": list(reversed(rows))}


class SkillContractTests(unittest.TestCase):
    def test_frontmatter_name_and_description(self):
        text = _text()
        self.assertTrue(text.startswith("---\n"))
        head = text.split("---", 2)[1]
        self.assertIn("name: technical-analyst", head)
        self.assertIn("NSE", head)

    def test_secrets_block_and_disclaimer(self):
        text = _text()
        self.assertIn("## Secrets", text)
        self.assertIn("angel_session.json", text)
        self.assertIn("This is analysis, not financial advice.", text)

    def test_resources_exist_and_are_named(self):
        text = _text()
        for rel in EXPECTED_RESOURCES:
            self.assertTrue((SKILL_DIR / rel).is_file(), rel)
            self.assertIn(rel, text)

    def test_contrarian_section_positioned_and_documented(self):
        text = _text()
        a = text.index("## Example Usage Scenarios")
        b = text.index("## Contrarian Confirmation Mode")
        c = text.index("## Resources")
        self.assertTrue(a < b < c)
        for token in (
            "CONFIRMED",
            "INSUFFICIENT_DATA",
            "weekly_key_reversal",
            "failed_extreme",
            "failed_breakout",
            "stop_reference",
            "ta_confirmation_<SYMBOL>_<as-of>.json",
            "check_weekly_price_action.py",
        ):
            self.assertIn(token, text)


class SmokeTests(unittest.TestCase):
    def _run(self, client, direction="CROWDED_LONG"):
        import check_weekly_price_action as cli

        with tempfile.TemporaryDirectory() as tmp:
            args = cli.parse_arguments(
                ["--symbol", "RELIANCE", "--direction", direction, "--as-of", "2026-11-10", "--output-dir", tmp]
            )
            out = cli.run(args, client=client)
            self.assertTrue((Path(tmp) / "ta_confirmation_RELIANCE_2026-11-10.json").is_file())
            self.assertTrue((Path(tmp) / "ta_confirmation_RELIANCE_2026-11-10.md").is_file())
        return out

    def test_end_to_end_with_fake_client(self):
        out = self._run(FakeClient())
        self.assertIn(out["verdict"], ("CONFIRMED", "NOT_CONFIRMED"))
        self.assertGreater(out["weekly_bars_used"], 30)

    def test_short_history_fails_closed(self):
        out = self._run(FakeClient(days=60))
        self.assertEqual(out["verdict"], "INSUFFICIENT_DATA")
        self.assertIsNone(out["checks"])

    def test_no_data_fails_closed(self):
        class Empty:
            def get_historical_prices(self, symbol, days=365):
                return None

        out = self._run(Empty())
        self.assertEqual(out["verdict"], "INSUFFICIENT_DATA")
        self.assertEqual(out["verdict_reason"], "no_price_source")

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)


if __name__ == "__main__":
    unittest.main()
