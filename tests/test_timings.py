"""Tests for timings.py against a hand-made ioreg dump (real captures have the same shape)."""
import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import timings  # noqa: E402


def elem(hz, vtot=1160, htot=2120, score='"Score"=16846,', precise=True):
    """One timing element the way ioreg -lw0 prints it (no spaces inside dicts)."""
    v = int(round(hz * 65536))
    hk = int(round(hz * vtot / 1000 * 65536))                       # line rate in kHz, same 1/65536 units
    pv = f'"PreciseSyncRate"={v - 65},' if precise else ""
    return ('{"HorizontalAttributes"={"Total"=%d,"Active"=1920,"PreciseSyncRate"=%d,"SyncRate"=%d},'
            '"VerticalAttributes"={"Total"=%d,"Active"=1080,%s"SyncRate"=%d},'
            '%s"UnsafeColorElementIDs"=()}' % (htot, hk - 3, hk, vtot, pv, v, score))


# Node 1: 360 and 300 usable, a 240 candidate that was dropped. Node 2 lists no Score keys at all.
IOREG = (
    '+-o AppleCLCD2  <class AppleCLCD2, id 0x100000abc, registered, matched, active>\n'
    '    | {\n'
    '    |   "TimingElements" = (' + elem(360) + ',' + elem(300, vtot=1144, htot=2080) + ')\n'
    '    |   "PreferredTimingElements" = (' + elem(360) + ',' + elem(300, vtot=1144, htot=2080) + ','
    + elem(240, vtot=1144, htot=2080) + ')\n'
    '    | }\n'
    '+-o AppleCLCD2  <class AppleCLCD2, id 0x100000def, registered, matched, active>\n'
    '    | {\n'
    '    |   "TimingElements" = (' + elem(60, vtot=1125, htot=2200, score="", precise=False) + ')\n'
    '    | }\n'
)


class Report(unittest.TestCase):
    def report(self, io_text, minhz=100.0):
        out = io.StringIO()
        rc = timings.report(io_text, minhz, out=out)
        return rc, out.getvalue()

    def test_marks_candidates_against_the_usable_table(self):
        rc, text = self.report(IOREG)
        self.assertEqual(rc, 0)
        self.assertIn("node id 0x100000abc   usable=2  candidates=3", text)
        lines = [l for l in text.splitlines() if "[usable]" in l or "[dropped]" in l]
        self.assertEqual(len(lines), 3)
        self.assertIn("[usable]", next(l for l in lines if "359.999Hz" in l))
        self.assertIn("[dropped]", next(l for l in lines if "239.999Hz" in l))
        self.assertIn("vblank=80", text)                            # 1160 - 1080
        self.assertIn("H=417.6kHz", text)                           # 360 * 1160 lines

    def test_min_hz_hides_slow_entries_and_missing_keys_are_fine(self):
        rc, text = self.report(IOREG, minhz=100)
        self.assertNotIn("60.000Hz", text)                          # node 2's only entry is under 100 Hz
        self.assertIn("node id 0x100000def   usable=1  candidates=0", text)
        rc, text = self.report(IOREG, minhz=0)
        self.assertIn("60.000Hz", text)
        self.assertIn("score=-1", text)                             # no Score key on that node

    def test_precise_rate_is_preferred_and_sync_rate_is_the_fallback(self):
        self.assertAlmostEqual(timings.rate({"PreciseSyncRate": 65536 * 3, "SyncRate": 65536}), 3.0)
        self.assertAlmostEqual(timings.rate({"SyncRate": 65536 * 2}), 2.0)
        self.assertAlmostEqual(timings.rate({"PreciseSyncRate": 0, "SyncRate": 65536 * 2}), 2.0)

    def test_no_timing_elements(self):
        rc, text = self.report("+-o Root  <class IORegistryEntry, id 0x100000100>\n")
        self.assertEqual(rc, 1)
        self.assertIn("no TimingElements", text)

    def test_element_without_axes_is_skipped(self):
        self.assertIsNone(timings.row('{"Score"=1}'))


if __name__ == "__main__":
    unittest.main()
