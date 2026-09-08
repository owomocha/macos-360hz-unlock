#!/usr/bin/env python3
"""Switch an external display to a target mode and count the real vsync rate.

    setmode.py --rate 360                 list candidate modes (1920 wide by default); no switch
    setmode.py --rate 360 0               switch to candidate 0 and measure for 5 s
    setmode.py revert --rate 300          switch to the mode at 300 Hz without measuring (undo)

Needs PyObjC's Quartz: pip install pyobjc-framework-Quartz
"""
import argparse
import sys
import time

import Quartz

TOLERANCE_HZ = 1.5          # 359.999 and 360.001 both count as 360


def modes(did):
    return Quartz.CGDisplayCopyAllDisplayModes(did, {"kCGDisplayShowDuplicateLowResolutionModes": True}) or []


def matching(did, width, rate, pixel_exact=False):
    """Usable desktop modes on `did` that are `width` wide and within TOLERANCE_HZ of `rate`."""
    out = []
    for m in modes(did):
        if (abs(Quartz.CGDisplayModeGetRefreshRate(m) - rate) < TOLERANCE_HZ
                and Quartz.CGDisplayModeGetWidth(m) == width
                and (not pixel_exact or Quartz.CGDisplayModeGetPixelWidth(m) == width)
                and Quartz.CGDisplayModeIsUsableForDesktopGUI(m)):
            out.append(m)
    return out


def find_display(width, rate, pixel_exact=False):
    err, ids, cnt = Quartz.CGGetOnlineDisplayList(16, None, None)
    for d in ids or []:
        if Quartz.CGDisplayIsBuiltin(d):
            continue
        c = matching(d, width, rate, pixel_exact)
        if c:
            return d, c
    return None, []


def describe(m):
    return (f"{Quartz.CGDisplayModeGetWidth(m)}x{Quartz.CGDisplayModeGetHeight(m)}"
            f" @{Quartz.CGDisplayModeGetRefreshRate(m):.4f}Hz"
            f"  pixels {Quartz.CGDisplayModeGetPixelWidth(m)}x{Quartz.CGDisplayModeGetPixelHeight(m)}"
            f"  ioModeID={Quartz.CGDisplayModeGetIODisplayModeID(m)}")


def switch(did, m):
    err, cfg = Quartz.CGBeginDisplayConfiguration(None)
    Quartz.CGConfigureDisplayWithDisplayMode(cfg, did, m, None)
    return Quartz.CGCompleteDisplayConfiguration(cfg, 1)      # kCGConfigureForSession: a reboot undoes it


def measure(did, seconds):
    """Count vsyncs with a CVDisplayLink output handler. Returns (counted_hz, median_ms, samples)."""
    err, link = Quartz.CVDisplayLinkCreateWithCGDisplay(did, None)
    nom = Quartz.CVDisplayLinkGetNominalOutputVideoRefreshPeriod(link)
    ts = []

    def handler(dl, now, out, fin, fout):
        ts.append(time.monotonic())
        return (0, 0)                                          # anything else crashes the process

    Quartz.CVDisplayLinkSetOutputHandler(link, handler)
    Quartz.CVDisplayLinkStart(link)
    time.sleep(seconds)
    act = Quartz.CVDisplayLinkGetActualOutputVideoRefreshPeriod(link)   # 0 unless a handler is installed
    Quartz.CVDisplayLinkStop(link)
    cur = Quartz.CGDisplayCopyDisplayMode(did)
    print(f"  mode reported     : {Quartz.CGDisplayModeGetRefreshRate(cur):.4f} Hz")
    if nom.timeValue:
        print(f"  nominal period    : {nom.timeScale / nom.timeValue:.4f} Hz")
    if len(ts) > 10:
        span = ts[-1] - ts[0]
        d = sorted(ts[i + 1] - ts[i] for i in range(len(ts) - 1))
        print(f"  vsync counted     : {(len(ts) - 1) / span:.4f} Hz  ({len(ts)} frames / {span:.3f} s)   <- actual output")
        print(f"  frame interval    : median {d[len(d) // 2] * 1000:.4f} ms")
    print(f"  CoreVideo actual  : {1 / act if act else 0:.4f} Hz")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", nargs="?", help="candidate index to switch to, or 'revert'")
    p.add_argument("--rate", type=float, required=True, help="refresh rate to look for (Hz)")
    p.add_argument("--width", type=int, default=1920, help="mode width in points (default 1920)")
    p.add_argument("--seconds", type=float, default=5, help="how long to count vsyncs (default 5)")
    a = p.parse_args(argv)

    revert = a.what == "revert"
    # revert picks blindly, so insist on the 1:1 mode rather than a scaled duplicate of it
    did, cands = find_display(a.width, a.rate, pixel_exact=revert)
    if did is None:
        print(f"no external display has a {a.width}-wide mode at {a.rate:g} Hz")
        return 1

    if revert:
        rc = switch(did, cands[0])
        print(f"switched display 0x{did:x} to {describe(cands[0])}  rc={rc}")
        return 0 if rc == 0 else 1

    print(f"display 0x{did:x}: {len(cands)} candidate(s) at {a.rate:g} Hz")
    for i, m in enumerate(cands):
        print(f"  [{i}] {describe(m)}")
    if a.what is None:
        print(f"\nto switch and measure: setmode.py --width {a.width} --rate {a.rate:g} <index>")
        return 0

    try:
        m = cands[int(a.what)]
    except (ValueError, IndexError):
        print(f"candidate must be an index 0..{len(cands) - 1}, not {a.what!r}", file=sys.stderr)
        return 2
    rc = switch(did, m)
    print(f"\nswitch rc={rc}")
    time.sleep(3)
    measure(did, a.seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
