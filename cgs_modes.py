#!/usr/bin/env python3
"""List every display mode through the private CGS API, including the ones
CGDisplayCopyAllDisplayModes hides.

    cgs_modes.py <display id>       e.g. cgs_modes.py 0x3

The descriptor layout is not guessed: offsets were pinned down by matching the
entries against the modes CoreGraphics does show.
"""
import ctypes
import sys

import Quartz

cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
cg.CGSGetNumberOfDisplayModes.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_int32)]
cg.CGSGetNumberOfDisplayModes.restype = ctypes.c_int32
cg.CGSGetDisplayModeDescriptionOfLength.argtypes = [ctypes.c_uint32, ctypes.c_int32,
                                                    ctypes.c_void_p, ctypes.c_int32]
cg.CGSGetDisplayModeDescriptionOfLength.restype = ctypes.c_int32

did = int(sys.argv[1], 0)
n = ctypes.c_int32(0)
rc = cg.CGSGetNumberOfDisplayModes(did, ctypes.byref(n))
print(f"CGSGetNumberOfDisplayModes rc={rc}  modes={n.value}")

cgmodes = Quartz.CGDisplayCopyAllDisplayModes(did, {"kCGDisplayShowDuplicateLowResolutionModes": True})
print(f"CGDisplayCopyAllDisplayModes shows {len(cgmodes)}")
print(f"-> hidden modes: {n.value - len(cgmodes)}")

SIZE = 0xD4
buf = (ctypes.c_ubyte * 512)()
rows = []
for i in range(n.value):
    ctypes.memset(buf, 0, 512)
    rc = cg.CGSGetDisplayModeDescriptionOfLength(did, i, ctypes.byref(buf), SIZE)
    if rc != 0:
        continue
    b = bytes(buf[:SIZE])
    u32 = lambda o: int.from_bytes(b[o:o + 4], "little")
    u16 = lambda o: int.from_bytes(b[o:o + 2], "little")
    rows.append((i, u32(0), u32(4), u32(8), u32(12), u32(16), u16(190), b))

print(f"\ndescriptors read: {len(rows)}   (showing >= 200 Hz or 1920x1080)")
print(f"{'idx':>4} {'mode':>5} {'flags':>10} {'width':>6} {'height':>6} {'depth':>5} {'freq':>5}")
for i, mode, flags, w, h, d, f, b in rows:
    if f >= 200 or (w == 1920 and h == 1080):
        print(f"{i:>4} {mode:>5} 0x{flags:08x} {w:>6} {h:>6} {d:>5} {f:>5}")
