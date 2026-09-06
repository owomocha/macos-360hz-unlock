#!/usr/bin/env python3
"""Generate an EDID with extra timings that macOS will accept.

Takes a monitor's stock EDID (hex text, e.g. `./vedid edid > edid/mine.hex`),
finds the DisplayID Type I timing block, drops the entries at the target rate
(those are the ones the DCP throws away) and adds candidates for the same
resolution and rate with longer blanking. Blocks 0 and 1 are left byte for byte;
both DisplayID checksums are recomputed.

    build_edid.py edid/pixio-px259ps.hex --rate 360
    build_edid.py edid/mine.hex --rate 240 --width 2560 --height 1440 -o edid/mine-240.hex

Why blanking: the DCP only accepts a timing whose vertical blanking *time* is
long enough (see README). Candidates are given as hblank x vblank counts and the
resulting times are printed, so you can see which ones stand a chance.
"""
import argparse
import pathlib
import sys

DEFAULT_BLANKING = "200x80,216x90,160x80,160x64"   # the four that got me 360 Hz; the first one becomes preferred
DEFAULT_SYNC = "48,64,3,5"                          # hfront, hsync, vfront, vsync (pixels / lines)
MIN_VBLANK_US = 155.0                               # lowest vertical blanking time I have seen the DCP accept


class BuildError(Exception):
    pass


def load_hex(path):
    txt = pathlib.Path(path).read_text()
    return bytes.fromhex("".join(ch for ch in txt if ch in "0123456789abcdefABCDEF"))


def type1_entry(pclk_hz, hact, hblank, hfp, hsw, vact, vblank, vfp, vsw, flags=0x04, hpol=0, vpol=1):
    """DisplayID 1.x Type I detailed timing, 20 bytes. Every field is stored minus one."""
    v = round(pclk_hz / 10_000) - 1
    if not 0 <= v < (1 << 24):
        raise BuildError(f"pixel clock {pclk_hz/1e6:.2f} MHz does not fit a Type I entry")

    def le16(x, hi=0):
        x = (x - 1) | (hi << 15)
        return bytes([x & 0xFF, (x >> 8) & 0xFF])

    return (bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, flags])
            + le16(hact) + le16(hblank) + le16(hfp, hpol) + le16(hsw)
            + le16(vact) + le16(vblank) + le16(vfp, vpol) + le16(vsw))


def type1_decode(e):
    """(pclk_hz, hact, hblank, vact, vblank, rate_hz) of a 20-byte Type I entry."""
    pc = ((e[2] << 16 | e[1] << 8 | e[0]) + 1) * 10_000
    ha = (e[5] << 8 | e[4]) + 1
    hb = (e[7] << 8 | e[6]) + 1
    va = (e[13] << 8 | e[12]) + 1
    vb = (e[15] << 8 | e[14]) + 1
    return pc, ha, hb, va, vb, pc / ((ha + hb) * (va + vb))


def parse_did(did):
    """DisplayID section -> (size, [(tag, rev, payload), ...])."""
    size = did[2]
    out, i, end = [], 5, 5 + size
    while i < end and did[i] != 0:
        tag, rev, ln = did[i], did[i + 1], did[i + 2]
        out.append((tag, rev, bytes(did[i + 3:i + 3 + ln])))
        i += 3 + ln
    return size, out


def max_pclk_mhz(base):
    """Max pixel clock from the base block's range-limits descriptor, or None."""
    for i in range(54, 126, 18):
        d = base[i:i + 18]
        if d[0] == 0 and d[1] == 0 and d[3] == 0xFD and d[9]:
            return d[9] * 10
    return None


def build(raw, rate, width=1920, height=1080, blanking=DEFAULT_BLANKING, sync=DEFAULT_SYNC,
          hpol=0, vpol=1, keep_native=False, force=False):
    """Return (edid_bytes, rows, dropped_rates, pclk_ceiling_mhz)."""
    if len(raw) < 256 or len(raw) % 128:
        raise BuildError(f"EDID length {len(raw)} is not a multiple of 128 bytes (need at least 2 blocks)")
    raw = bytearray(raw)
    orig = bytes(raw)
    nblocks = len(raw) // 128
    didx = next((b for b in range(1, nblocks) if raw[b * 128] == 0x70), None)
    if didx is None:
        raise BuildError("no DisplayID extension block (tag 0x70); only DisplayID Type I timings are handled "
                         "so far. Open an issue with your EDID if yours lives in a Type VII block or a CTA DTD.")
    did = bytearray(raw[didx * 128:(didx + 1) * 128])
    size, blocks = parse_did(did)
    t1s = [b for b in blocks if b[0] == 0x03]
    if not t1s:
        raise BuildError("the DisplayID block has no Type I timing data block (tag 0x03)")
    t1 = t1s[0]
    others = [b for b in blocks if b[0] != 0x03]

    keep, dropped = b"", []
    payload = t1[2]
    for k in range(0, len(payload) - len(payload) % 20, 20):
        e = payload[k:k + 20]
        r = type1_decode(e)[5]
        if keep_native or abs(r - rate) > 2.0:
            keep += e
        else:
            dropped.append(r)

    try:
        hfp, hsw, vfp, vsw = (int(x) for x in sync.split(","))
        pairs = [tuple(int(x) for x in item.lower().split("x")) for item in blanking.split(",")]
    except ValueError:
        raise BuildError("--blanking wants hblank x vblank pairs like 200x80,160x64 and --sync wants 4 integers")
    cap = max_pclk_mhz(raw[:128])
    rows, new = [], b""
    for n, (hb, vb) in enumerate(pairs):
        ht, vt = width + hb, height + vb
        pclk = round(ht * vt * rate / 10_000) * 10_000          # Type I stores 10 kHz units
        hz, hk = pclk / (ht * vt), pclk / ht
        flags = 0x84 if n == 0 else 0x04                          # first candidate = preferred
        new += type1_entry(pclk, width, hb, hfp, hsw, height, vb, vfp, vsw, flags=flags, hpol=hpol, vpol=vpol)
        row = dict(name=chr(ord("A") + n), ht=ht, vt=vt, hb=hb, vb=vb, pclk_mhz=pclk / 1e6, h_khz=hk / 1e3,
                   hz=hz, vblank_us=vb / hk * 1e6, hblank_us=hb / pclk * 1e6, gbps=pclk * 24 / 1e9,
                   preferred=(n == 0))
        rows.append(row)
        if cap and pclk > cap * 1e6 and not force:
            raise BuildError(f"candidate {row['name']}: pixel clock {pclk/1e6:.2f} MHz is above the {cap} MHz "
                             f"this EDID declares as its maximum (--force to override)")

    body = keep + new
    newblocks = bytes([0x03, t1[1], len(body)]) + body
    for tag, rev, pl in others:
        newblocks += bytes([tag, rev, len(pl)]) + pl
    if len(newblocks) > size:
        raise BuildError(f"the DisplayID section holds {size} bytes and the timings need {len(newblocks)}; "
                         f"use fewer candidates (--blanking)")
    did[5:5 + size] = newblocks + b"\x00" * (size - len(newblocks))
    did[126] = 0
    did[126] = (256 - sum(did[1:5 + size]) % 256) % 256        # DisplayID section checksum
    did[127] = 0
    did[127] = (256 - sum(did) % 256) % 256                    # EDID extension block checksum
    raw[didx * 128:(didx + 1) * 128] = did

    for b in range(nblocks):
        assert sum(raw[b * 128:(b + 1) * 128]) % 256 == 0, f"block {b} checksum"
    assert sum(did[1:127]) % 256 == 0, "DisplayID checksum"
    assert raw[:didx * 128] == orig[:didx * 128], "blocks before the DisplayID block must stay untouched"
    return bytes(raw), rows, dropped, cap


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("edid", help="stock EDID as hex text (./vedid edid > file)")
    p.add_argument("--rate", type=float, required=True, help="target refresh rate in Hz")
    p.add_argument("--width", type=int, default=1920, help="active pixels per line (default 1920)")
    p.add_argument("--height", type=int, default=1080, help="active lines (default 1080)")
    p.add_argument("--blanking", default=DEFAULT_BLANKING,
                   help=f"candidate hblank x vblank pairs, comma separated; the first becomes preferred "
                        f"(default {DEFAULT_BLANKING})")
    p.add_argument("--sync", default=DEFAULT_SYNC, help=f"hfront,hsync,vfront,vsync (default {DEFAULT_SYNC})")
    p.add_argument("--hpol", type=int, default=0, help="hsync polarity bit (default 0)")
    p.add_argument("--vpol", type=int, default=1, help="vsync polarity bit (default 1)")
    p.add_argument("--keep-native", action="store_true",
                   help="keep the monitor's own entries at the target rate instead of dropping them")
    p.add_argument("--force", action="store_true", help="ignore the pixel-clock ceiling from the EDID's range limits")
    p.add_argument("-o", "--out", help="output hex file (default: <input stem>-<rate>.hex next to the input)")
    a = p.parse_args(argv)

    src = pathlib.Path(a.edid)
    try:
        raw = load_hex(src)
        out_bytes, rows, dropped, cap = build(raw, a.rate, a.width, a.height, a.blanking, a.sync,
                                             a.hpol, a.vpol, a.keep_native, a.force)
    except (BuildError, AssertionError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out = pathlib.Path(a.out) if a.out else src.with_name(f"{src.stem}-{a.rate:g}.hex")
    out.write_text(out_bytes.hex())

    print(f"input : {src}  ({len(raw)} bytes, {len(raw) // 128} blocks)")
    if dropped:
        print(f"dropped {len(dropped)} native entr{'y' if len(dropped) == 1 else 'ies'} at the target rate: "
              + ", ".join(f"{r:.3f} Hz" for r in dropped))
    print(f"pixel clock ceiling from the EDID: {cap} MHz" if cap else "no range-limits descriptor: pixel clock unchecked")
    print(f"\ncandidates for {a.width}x{a.height} @ {a.rate:g} Hz")
    print(f"{'':2} {'htotal':>7} {'vtotal':>7} {'hbl':>4} {'vbl':>4} {'pclk MHz':>9} {'H kHz':>7} {'Hz':>9} "
          f"{'vblank us':>10} {'hblank us':>10} {'Gbps':>6}")
    for r in rows:
        note = "  <- preferred" if r["preferred"] else ""
        if r["vblank_us"] < MIN_VBLANK_US:
            note += f"  (vblank under {MIN_VBLANK_US:g} us: likely rejected)"
        print(f"{r['name']:2} {r['ht']:>7} {r['vt']:>7} {r['hb']:>4} {r['vb']:>4} {r['pclk_mhz']:>9.2f} "
              f"{r['h_khz']:>7.1f} {r['hz']:>9.4f} {r['vblank_us']:>10.1f} {r['hblank_us']:>10.3f} "
              f"{r['gbps']:>6.2f}{note}")
    changed = sum(1 for i in range(len(raw)) if out_bytes[i] != raw[i])
    print(f"\nwrote {out}  ({changed} bytes changed, all inside the DisplayID block)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
