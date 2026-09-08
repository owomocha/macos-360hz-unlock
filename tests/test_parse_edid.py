"""Tests for parse_edid.py: the shipped EDIDs decode sanely, and odd blocks don't trip it."""
import contextlib
import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_edid as be  # noqa: E402
import parse_edid as pe  # noqa: E402
from test_build_edid import did_block  # noqa: E402

STOCK = ROOT / "edid" / "pixio-px259ps.hex"
SHIPPED = ROOT / "edid" / "pixio-px259ps-360.hex"


def dump(raw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pe.dump(raw)
    return out.getvalue()


def with_checksum(blk):
    blk = bytearray(blk)
    blk[127] = (256 - sum(blk[:127]) % 256) % 256
    return bytes(blk)


class ShippedEdids(unittest.TestCase):
    def test_stock(self):
        text = dump(pe.load_hex(STOCK))
        self.assertIn("manufacturer PXO", text)
        self.assertIn("input: digital  10 bits/color  DisplayPort", text)
        self.assertIn("[range] V 48-360Hz", text)
        self.assertIn("[CTA DTD3] 1920x1080p @200.000Hz", text)
        self.assertIn("DisplayID 1.2  section size 121", text)
        self.assertIn("@ 359.997Hz", text)
        self.assertIn("PREFERRED", text)
        self.assertIn("tag=0x07 (VESA timing standard)", text)
        self.assertEqual(text.count("checksum ok"), 3)
        self.assertNotIn("tag=0x00", text)                          # the padding is not data blocks

    def test_generated(self):
        text = dump(pe.load_hex(SHIPPED))
        self.assertEqual(text.count("Type I: 1920x1080"), 5)       # stock 300 + candidates A-D
        self.assertEqual(text.count("checksum ok"), 3)
        self.assertNotIn("tag=0x00", text)


class OddBlocks(unittest.TestCase):
    def setUp(self):
        self.base = pe.load_hex(STOCK)[:128]

    def test_bad_checksum_is_called_out(self):
        bad = bytearray(self.base)
        bad[100] ^= 0x01
        self.assertIn("checksum BAD", dump(bytes(bad)))
        self.assertIn("checksum ok", dump(self.base))

    def test_cta_block_with_no_dtds_and_no_data_blocks(self):
        cta = with_checksum(bytes([0x02, 0x03, 0x00, 0x00]) + b"\x00" * 124)   # d = 0
        text = dump(self.base + cta)
        self.assertIn("DTDs start at 0x00", text)
        self.assertNotIn("[CTA DTD", text)                          # the header must not be read as a DTD

    def test_text_descriptor_and_extension_count_mismatch(self):
        blk = bytearray(self.base)
        blk[108:126] = b"\x00\x00\x00\xfe\x00" + b"hello there  ".ljust(13)
        blk[126] = 5                                                # claims 5 extensions, file has 0
        text = dump(with_checksum(blk))
        self.assertIn("[text] hello there", text)
        self.assertIn("extension blocks 5 (file has 0)", text)

    def test_displayid_with_a_leading_product_id_block(self):
        entry = be.type1_entry(885_310_000, 1920, 200, 48, 64, 1080, 80, 3, 5, flags=0x84)
        section = did_block([(0x00, 0x00, bytes(12)), (0x03, 0x01, entry)])
        text = dump(self.base + section)
        self.assertIn("tag=0x00 (Product ID)", text)
        self.assertIn("Type I: 1920x1080 @ 359.999Hz", text)
        self.assertIn("PREFERRED", text)
        self.assertEqual(text.count("data block tag="), 2)


class Cli(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pe.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_usage_without_a_file(self):
        rc, out, err = self.run_main([])
        self.assertEqual(rc, 1)
        self.assertIn("parse_edid.py edid/", err)

    def test_missing_and_truncated_files(self):
        rc, out, err = self.run_main([str(ROOT / "edid" / "nope.hex")])
        self.assertEqual(rc, 1)
        self.assertIn("error:", err)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / "short.hex"
            src.write_text(STOCK.read_text()[:200])
            rc, out, err = self.run_main([str(src)])
            self.assertEqual(rc, 1)
            self.assertIn("not a whole number of 128-byte", err)

    def test_decodes_a_file(self):
        rc, out, err = self.run_main([str(STOCK)])
        self.assertEqual(rc, 0)
        self.assertIn("EDID 384 bytes = 3 blocks", out)


if __name__ == "__main__":
    unittest.main()
