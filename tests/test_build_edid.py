"""Tests for build_edid.py. `make test` or `python3 -m unittest discover -s tests`."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_edid as be  # noqa: E402

STOCK = ROOT / "edid" / "pixio-px259ps.hex"
SHIPPED = ROOT / "edid" / "pixio-px259ps-360.hex"


def did_block(blocks, version=0x12, size=121):
    """A 128-byte DisplayID extension block holding `blocks` = [(tag, rev, payload), ...]."""
    body = b"".join(bytes([tag, rev, len(pl)]) + pl for tag, rev, pl in blocks)
    assert len(body) <= size
    blk = bytearray([0x70, version, size, 0, 0]) + body + b"\x00" * (size - len(body)) + b"\x00\x00"
    blk[126] = (256 - sum(blk[1:5 + size]) % 256) % 256
    blk[127] = (256 - sum(blk) % 256) % 256
    return bytes(blk)


def did_blocks(raw):
    """Parsed data blocks of the first DisplayID extension in `raw`."""
    didx = next(b for b in range(1, len(raw) // 128) if raw[b * 128] == 0x70)
    return be.parse_did(bytearray(raw[didx * 128:(didx + 1) * 128]))[1]


def type1_entries(raw):
    """Decoded Type I entries and their flag bytes from the first DisplayID block."""
    payload = next(b for b in did_blocks(raw) if b[0] == 0x03)[2]
    ks = range(0, len(payload) - len(payload) % 20, 20)
    return [be.type1_decode(payload[k:k + 20]) for k in ks], [payload[k + 3] for k in ks]


def near(entries, hz):
    return [e for e in entries if abs(e[5] - hz) < 1.5]


class BuildEdid(unittest.TestCase):
    def setUp(self):
        self.raw = be.load_hex(STOCK)

    def test_reproduces_the_shipped_edid_byte_for_byte(self):
        out, rows, dropped, cap = be.build(self.raw, 360)
        self.assertEqual(out, be.load_hex(SHIPPED))
        self.assertEqual(cap, 900)
        self.assertEqual(len(dropped), 1)               # the monitor's own (rejected) 360 Hz entry
        self.assertAlmostEqual(dropped[0], 360, delta=0.01)

    def test_checksums_and_untouched_blocks(self):
        out, *_ = be.build(self.raw, 360)
        for b in range(len(out) // 128):
            self.assertEqual(sum(out[b * 128:(b + 1) * 128]) % 256, 0, f"block {b}")
        self.assertEqual(out[:256], self.raw[:256])
        self.assertEqual(len(out), len(self.raw))

    def test_candidates_and_preferred_flag(self):
        out, rows, *_ = be.build(self.raw, 360)
        entries, flags = type1_entries(out)
        self.assertEqual(len(near(entries, 360)), 4)
        self.assertEqual(len(near(entries, 300)), 1)    # the stock 300 Hz entry survives
        self.assertEqual([f & 0x80 for f in flags], [0, 0x80, 0, 0, 0])   # first candidate is preferred
        self.assertEqual([r["name"] for r in rows], ["A", "B", "C", "D"])
        self.assertAlmostEqual(rows[0]["pclk_mhz"], 885.31, delta=0.01)
        self.assertAlmostEqual(rows[0]["vblank_us"], 191.6, delta=0.1)

    def test_other_rate_resolution_and_blanking(self):
        out, rows, *_ = be.build(self.raw, 240, width=1920, height=1080, blanking="200x80,160x64")
        entries, _ = type1_entries(out)
        self.assertEqual(len(near(entries, 240)), 2)
        self.assertEqual(near(entries, 240)[0][1], 1920)
        self.assertEqual(near(entries, 240)[0][3], 1080)
        self.assertAlmostEqual(rows[0]["hz"], 240, delta=0.01)
        out2, rows2, *_ = be.build(self.raw, 144, width=2560, height=1440, blanking="160x40")
        self.assertEqual(near(type1_entries(out2)[0], 144)[0][1:5], (2560, 160, 1440, 40))
        self.assertAlmostEqual(rows2[0]["hz"], 144, delta=0.01)

    def test_keep_native(self):
        out, rows, dropped, _ = be.build(self.raw, 360, keep_native=True, blanking="200x80,216x90,160x80")
        self.assertEqual(dropped, [])
        self.assertEqual(len(near(type1_entries(out)[0], 360)), 4)   # native + 3 candidates

    def test_refuses_when_the_section_is_full(self):
        with self.assertRaises(be.BuildError):
            be.build(self.raw, 360, keep_native=True)                 # native + 4 does not fit

    def test_pixel_clock_ceiling_from_the_edid(self):
        with self.assertRaises(be.BuildError):
            be.build(self.raw, 500)                                   # 1920x1080 @ 500 needs > 900 MHz
        # at 500 Hz neither stock entry is dropped, so only two candidates fit alongside them
        out, rows, *_ = be.build(self.raw, 500, force=True, blanking="200x80,160x64")
        self.assertEqual(len(out), len(self.raw))
        self.assertGreater(rows[0]["pclk_mhz"], 900)

    def test_needs_a_displayid_block(self):
        with self.assertRaises(be.BuildError):
            be.build(self.raw[:256], 360)

    def test_bad_arguments(self):
        with self.assertRaises(be.BuildError):
            be.build(self.raw, 360, blanking="200-80")
        with self.assertRaises(be.BuildError):
            be.build(self.raw[:200], 360)


class DisplayIdSection(unittest.TestCase):
    """Sections that look nothing like the Pixio's: other blocks around the timings."""

    def setUp(self):
        stock = be.load_hex(STOCK)
        self.head = stock[:256]                                     # base + CTA, untouched by build()
        self.entries = next(b for b in did_blocks(stock) if b[0] == 0x03)[2]   # its 300 and 360 Hz
        self.product_id = (0x00, 0x00, bytes(range(12)))            # DisplayID 1.x Product ID, tag 0

    def test_parse_did_stops_at_padding_not_at_a_zero_tag(self):
        section = did_block([self.product_id, (0x03, 0x01, self.entries)])
        size, blocks = be.parse_did(bytearray(section))
        self.assertEqual([b[0] for b in blocks], [0x00, 0x03])
        self.assertEqual(blocks[0][2], bytes(range(12)))

    def test_leading_product_id_block_keeps_its_place(self):
        raw = self.head + did_block([self.product_id, (0x03, 0x01, self.entries), (0x07, 0x00, b"\x08" * 10)])
        out, rows, dropped, _ = be.build(raw, 360, blanking="200x80,160x64")   # 4 would not fit beside them
        blocks = did_blocks(out)
        self.assertEqual([b[0] for b in blocks], [0x00, 0x03, 0x07])
        self.assertEqual(blocks[0], self.product_id)
        self.assertEqual(blocks[2][2], b"\x08" * 10)
        self.assertEqual(len(near(type1_entries(out)[0], 360)), 2)
        self.assertEqual(len(dropped), 1)

    def test_second_type_i_block_survives(self):
        second = (0x03, 0x01, self.entries[:20])                    # another block with the 300 Hz entry
        raw = self.head + did_block([(0x03, 0x01, self.entries), second])
        out, *_ = be.build(raw, 360, blanking="200x80")
        blocks = did_blocks(out)
        self.assertEqual([b[0] for b in blocks], [0x03, 0x03])
        self.assertEqual(blocks[1], second)

    def test_too_many_candidates_is_the_size_error(self):
        raw = self.head + did_block([(0x03, 0x01, self.entries)])
        with self.assertRaises(be.BuildError) as cm:
            be.build(raw, 360, blanking=",".join(["200x80"] * 13))
        self.assertIn("holds 121 bytes", str(cm.exception))


class Cli(unittest.TestCase):
    def run_main(self, argv):
        import contextlib, io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = be.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_main_writes_the_default_output_name(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / "mon.hex"
            src.write_text(STOCK.read_text())
            rc, out, err = self.run_main([str(src), "--rate", "360"])
            self.assertEqual(rc, 0)
            self.assertIn("<- preferred", out)
            self.assertEqual(be.load_hex(pathlib.Path(d) / "mon-360.hex"), be.load_hex(SHIPPED))

    def test_main_reports_errors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / "mon.hex"
            src.write_text(STOCK.read_text()[:512])       # base + CTA only
            rc, out, err = self.run_main([str(src), "--rate", "360"])
            self.assertEqual(rc, 1)
            self.assertIn("no DisplayID extension block", err)


if __name__ == "__main__":
    unittest.main()
