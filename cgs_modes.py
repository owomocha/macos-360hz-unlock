#!/usr/bin/env python3
"""List every display mode through the private CGS API, including the ones
CGDisplayCopyAllDisplayModes hides.

    cgs_modes.py <display id> [min_hz]      e.g. cgs_modes.py 0x3 200   (default: show >= 100 Hz)

The descriptor layout is not guessed: offsets were pinned down by matching the
entries against the modes CoreGraphics does show.
"""
import ctypes
import sys

import Quartz

SIZE = 0xD4                                            # bytes of descriptor CGS fills in per mode


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        did = int(argv[0], 0)
        minhz = float(argv[1]) if len(argv) > 1 else 100.0
    except (IndexError, ValueError):
        print(__doc__.strip(), file=sys.stderr)
        return 2

    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cg.CGSGetNumberOfDisplayModes.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_int32)]
    cg.CGSGetNumberOfDisplayModes.restype = ctypes.c_int32
    cg.CGSGetDisplayModeDescriptionOfLength.argtypes = [ctypes.c_uint32, ctypes.c_int32,
                                                        ctypes.c_void_p, ctypes.c_int32]
    cg.CGSGetDisplayModeDescriptionOfLength.restype = ctypes.c_int32

    n = ctypes.c_int32(0)
    rc = cg.CGSGetNumberOfDisplayModes(did, ctypes.byref(n))
    print(f"CGSGetNumberOfDisplayModes rc={rc}  modes={n.value}")
    if rc != 0:
        return 1

    cgmodes = Quartz.CGDisplayCopyAllDisplayModes(did, {"kCGDisplayShowDuplicateLowResolutionModes": True}) or []
    print(f"CGDisplayCopyAllDisplayModes shows {len(cgmodes)}")
    print(f"-> hidden modes: {n.value - len(cgmodes)}")

    buf = (ctypes.c_ubyte * 512)()
    rows = []
    for i in range(n.value):
        ctypes.memset(buf, 0, 512)
        if cg.CGSGetDisplayModeDescriptionOfLength(did, i, ctypes.byref(buf), SIZE) != 0:
            continue
        b = bytes(buf[:SIZE])
        u32 = lambda o: int.from_bytes(b[o:o + 4], "little")
        u16 = lambda o: int.from_bytes(b[o:o + 2], "little")
        rows.append((i, u32(0), u32(4), u32(8), u32(12), u32(16), u16(190)))

    print(f"\ndescriptors read: {len(rows)}   (showing >= {minhz:g} Hz, fastest first)")
    print(f"{'idx':>4} {'mode':>5} {'flags':>10} {'width':>6} {'height':>6} {'depth':>5} {'freq':>5}")
    for i, mode, flags, w, h, d, f in sorted(rows, key=lambda r: (-r[6], -r[3], r[0])):
        if f >= minhz:
            print(f"{i:>4} {mode:>5} 0x{flags:08x} {w:>6} {h:>6} {d:>5} {f:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
