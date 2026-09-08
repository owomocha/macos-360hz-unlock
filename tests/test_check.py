"""Tests for check.py's DCP table check. Quartz is stubbed: nothing here touches a display."""
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("Quartz", types.ModuleType("Quartz"))    # check/setmode import it at top level
import check  # noqa: E402
from test_timings import IOREG  # noqa: E402


class DcpUsableTable(unittest.TestCase):
    def test_finds_the_usable_rates_within_tolerance(self):
        self.assertTrue(check.dcp_usable_table_has(360, IOREG))
        self.assertTrue(check.dcp_usable_table_has(359.99, IOREG))     # SyncRate is 0.5 Hz steps
        self.assertTrue(check.dcp_usable_table_has(300, IOREG))
        self.assertTrue(check.dcp_usable_table_has(60, IOREG))

    def test_a_candidate_that_was_dropped_does_not_count(self):
        self.assertFalse(check.dcp_usable_table_has(240, IOREG))       # only in PreferredTimingElements

    def test_the_horizontal_sync_rate_is_not_a_vertical_one(self):
        # the 360 Hz element's line rate is 417.6 kHz and sits under the same "SyncRate" key
        self.assertFalse(check.dcp_usable_table_has(417.6, IOREG))
        self.assertFalse(check.dcp_usable_table_has(343.2, IOREG))     # the 300 Hz element's line rate

    def test_nothing_in_the_registry(self):
        self.assertFalse(check.dcp_usable_table_has(360, ""))


if __name__ == "__main__":
    unittest.main()
