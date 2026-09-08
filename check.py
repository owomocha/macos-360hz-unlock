#!/usr/bin/env python3
"""One-shot status: is the target mode in the DCP's usable table, and does CoreGraphics see it?

    check.py --rate 360 [--width 1920]      report only; exit 1 if the mode is not there
    check.py --rate 360 --set               also switch to it and measure (runs setmode.py)

Normally the LaunchAgent (com.local.display360) keeps the mode applied; if this
says no, ./enable.sh applies it by hand.

Needs PyObjC's Quartz: pip install pyobjc-framework-Quartz
"""
import argparse
import pathlib
import re
import subprocess
import sys

import Quartz

from setmode import TOLERANCE_HZ, matching, modes


def dcp_usable_table_has(rate, ioreg=None):
    """Is there a TimingElements entry within TOLERANCE_HZ of `rate`?

    SyncRate is 1/65536 Hz rounded to 0.5 Hz steps, so it is compared with a tolerance,
    not for equality. Only the VerticalAttributes value counts: HorizontalAttributes has
    a SyncRate too, the line rate in kHz, and a 295 kHz line rate is not a 295 Hz mode.
    """
    if ioreg is None:
        ioreg = subprocess.run(["ioreg", "-lw0"], capture_output=True, text=True).stdout
    for m in re.finditer(r'"TimingElements" = \(', ioreg):
        i = m.end() - 1
        depth, j = 0, i
        while j < len(ioreg):
            if ioreg[j] == "(":
                depth += 1
            elif ioreg[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        for v in re.findall(r'"VerticalAttributes"=\{[^{}]*"SyncRate"=(\d+)', ioreg[i:j]):
            if abs(int(v) / 65536 - rate) < TOLERANCE_HZ:
                return True
    return False


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rate", type=float, required=True, help="refresh rate to look for (Hz)")
    p.add_argument("--width", type=int, default=1920, help="mode width in points (default 1920)")
    p.add_argument("--set", action="store_true", help="switch to the mode and measure if it exists")
    a = p.parse_args(argv)

    print(f"[1] DCP usable table (TimingElements) has {a.rate:g} Hz : {'yes' if dcp_usable_table_has(a.rate) else 'no'}")

    err, ids, cnt = Quartz.CGGetOnlineDisplayList(16, None, None)
    target = None
    for did in ids or []:
        ms = modes(did)
        rates = sorted({round(Quartz.CGDisplayModeGetRefreshRate(m), 2) for m in ms}, reverse=True)
        cur = Quartz.CGDisplayCopyDisplayMode(did)
        builtin = bool(Quartz.CGDisplayIsBuiltin(did))
        print(f"\n[2] display 0x{did:x}{' (built-in)' if builtin else ''}: now "
              f"{Quartz.CGDisplayModeGetWidth(cur)}x{Quartz.CGDisplayModeGetHeight(cur)} "
              f"@{Quartz.CGDisplayModeGetRefreshRate(cur):.2f} Hz")
        print(f"    selectable rates: {rates}")
        if not builtin:
            c = matching(did, a.width, a.rate)
            if c:
                target = (did, c[0])                   # the one `--set` (setmode.py ... 0) switches to

    print("\n" + "=" * 62)
    if target is None:
        print(f"verdict: no {a.width}-wide {a.rate:g} Hz mode. The virtual EDID is not in (or was rejected).")
        print("  apply now : ./enable.sh <edid.hex> <width> <rate>")
        print("  agent     : launchctl print gui/$(id -u)/com.local.display360")
        print("  log       : ./display360.log")
        return 1
    did, m = target
    print(f"verdict: {Quartz.CGDisplayModeGetWidth(m)}x{Quartz.CGDisplayModeGetHeight(m)} "
          f"@{Quartz.CGDisplayModeGetRefreshRate(m):.3f} Hz is selectable on display 0x{did:x}")
    if not a.set:
        print(f"  switch and measure: python3 setmode.py --width {a.width} --rate {a.rate:g} 0")
        return 0
    setmode = pathlib.Path(__file__).with_name("setmode.py")
    return subprocess.call([sys.executable, str(setmode), "--width", str(a.width), "--rate", f"{a.rate:g}", "0"])


if __name__ == "__main__":
    sys.exit(main())
