#!/usr/bin/env python3
"""Decode every block of an EDID (base, CTA-861, DisplayID) and print the timings.
Handy for finding where a monitor keeps its high-rate timing before you rewrite it.

    parse_edid.py edid/pixio-px259ps.hex
"""
import sys

HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"
BIT_DEPTH = {1: 6, 2: 8, 3: 10, 4: 12, 5: 14, 6: 16}                 # video input byte, bits 6:4
INTERFACE = {1: "DVI", 2: "HDMI-a", 3: "HDMI-b", 4: "MDDI", 5: "DisplayPort"}
CTA_BLOCKS = {1: "Audio", 2: "Video(VIC)", 3: "Vendor", 4: "SpeakerAlloc", 7: "Extended"}
CTA_EXT = {0: "VideoCap", 5: "Colorimetry", 6: "HDRstatic", 7: "HDRdynamic", 0x0d: "VideoFormatPref",
           0x0e: "YCbCr420", 0x0f: "YCbCr420CapMap", 0x22: "DisplayID Type VII", 0x23: "DisplayID Type VIII",
           0x78: "HF-EEODB", 0x79: "HF-SCDB"}
DID_BLOCKS = {                                                      # DisplayID 1.x tags, then 2.x
    0x00: "Product ID", 0x01: "Display params", 0x02: "Color characteristics", 0x03: "Type I timing",
    0x04: "Type II timing", 0x05: "Type III timing", 0x06: "Type IV timing", 0x07: "VESA timing standard",
    0x08: "CEA timing standard", 0x09: "Video timing range limits", 0x0a: "Product serial",
    0x0b: "ASCII string", 0x0c: "Display device data", 0x0d: "Interface power sequencing",
    0x0e: "Transfer characteristics", 0x0f: "Display interface", 0x10: "Stereo display interface",
    0x11: "Type V timing (short)", 0x12: "Tiled display topology", 0x13: "Type VI timing",
    0x20: "Product ID", 0x21: "Display params", 0x22: "Type VII timing (detailed)",
    0x23: "Type VIII timing (enumerated)", 0x24: "Type IX timing (formula)",
    0x25: "Dynamic video timing range limits", 0x26: "Display interface features",
    0x27: "Stereo display interface", 0x28: "Tiled display topology", 0x29: "ContainerID",
    0x2a: "Type X timing (formula)", 0x7e: "Vendor specific", 0x7f: "Vendor specific"}


def load_hex(path):
    with open(path) as f:
        return bytes.fromhex("".join(ch for ch in f.read() if ch in "0123456789abcdefABCDEF"))


def checksum(blk):
    return "checksum ok" if sum(blk) % 256 == 0 else f"checksum BAD (sum mod 256 = {sum(blk) % 256})"


def dtd(b, label):
    pc = (b[1] << 8 | b[0]) * 10000                    # 10 kHz units
    if pc == 0:
        return None
    ha = b[2] | ((b[4] & 0xF0) << 4); hb = b[3] | ((b[4] & 0x0F) << 8)
    va = b[5] | ((b[7] & 0xF0) << 4); vb = b[6] | ((b[7] & 0x0F) << 8)
    ht, vt = ha + hb, va + vb
    hz = pc / (ht * vt) if ht and vt else 0
    intl = "i" if b[17] & 0x80 else "p"
    print(f"  [{label}] {ha}x{va}{intl} @{hz:7.3f}Hz  pclk {pc/1e6:7.3f}MHz  "
          f"total {ht}x{vt}  hblank {hb} vblank {vb}")
    return hz


def base_block(b0, nblocks):
    print(f"=== block 0: base EDID  ({checksum(b0)}) ===")
    if b0[:8] != HEADER:
        print("  header is not 00 ff ff ff ff ff ff 00: this may not be an EDID at all")
    mfg = b0[8] << 8 | b0[9]
    ext = b0[126]
    print(f"  manufacturer {chr((mfg >> 10 & 31) + 64)}{chr((mfg >> 5 & 31) + 64)}{chr((mfg & 31) + 64)}"
          f" ({b0[8]:02x}{b0[9]:02x})  product 0x{b0[11] << 8 | b0[10]:04x}  serial 0x{int.from_bytes(b0[12:16], 'little'):08x}"
          f"  EDID {b0[18]}.{b0[19]}  extension blocks {ext}"
          + (f" (file has {nblocks - 1})" if ext != nblocks - 1 else ""))
    vid = b0[20]
    if vid & 0x80:
        depth = BIT_DEPTH.get((vid >> 4) & 7, "undefined")
        print(f"  input: digital  {depth} bits/color  {INTERFACE.get(vid & 0xF, f'interface {vid & 0xF}')}")
    else:
        print("  input: analog")
    for i in range(4):
        o = 54 + i * 18
        d = b0[o:o + 18]
        if d[0] or d[1]:
            dtd(d, f"base DTD{i}")
        elif d[3] == 0xFC:
            print(f"  [name] {d[5:18].decode('ascii', 'replace').strip()}")
        elif d[3] == 0xFF:
            print(f"  [serial] {d[5:18].decode('ascii', 'replace').strip()}")
        elif d[3] == 0xFE:
            print(f"  [text] {d[5:18].decode('ascii', 'replace').strip()}")
        elif d[3] == 0xFD:
            off = d[4]   # EDID 1.4 range-limit offset flags: bit0/1 = V min/max +255, bit2/3 = H min/max +255
            vmin = d[5] + (255 if off & 0x01 else 0); vmax = d[6] + (255 if off & 0x02 else 0)
            hmin = d[7] + (255 if off & 0x04 else 0); hmax = d[8] + (255 if off & 0x08 else 0)
            print(f"  [range] V {vmin}-{vmax}Hz  H {hmin}-{hmax}kHz  maxPclk {d[9] * 10}MHz  offsets=0x{off:02x}")
        elif d[3] != 0x10:                             # 0x10 is the dummy descriptor, nothing to say
            print(f"  [descriptor 0x{d[3]:02x}] {d[5:18].hex()}")


def cta_block(blk):
    rev, dtdoff = blk[1], blk[2]
    print(f"  rev {rev}  DTDs start at 0x{dtdoff:02x}  flags 0x{blk[3]:02x} (native DTDs {blk[3] & 0xF})")
    p = 4
    while p < dtdoff:
        t, ln = blk[p] >> 5, blk[p] & 0x1F
        body = blk[p + 1:p + 1 + ln]
        extra = ""
        if t == 3 and len(body) >= 3:
            oui = body[2] << 16 | body[1] << 8 | body[0]
            extra = f" OUI=0x{oui:06x}" + (" [HDMI 1.4 VSDB]" if oui == 0x000c03
                                           else " [HDMI 2.1 HF-VSDB]" if oui == 0xc45dd8 else "")
            if oui == 0xc45dd8 and len(body) >= 7:
                extra += f" MaxFRL={body[6] >> 4} (0=none,1=3G3L,2=6G3L,3=6G4L,4=8G4L,5=10G4L,6=12G4L)"
            if oui == 0x000c03 and len(body) >= 7:
                extra += f" MaxTMDS={body[6] * 5}MHz"
        if t == 7 and body:
            extra = f" ext=0x{body[0]:02x} {CTA_EXT.get(body[0], '')}"
        print(f"  data block t={t}({CTA_BLOCKS.get(t, '?')}) len={ln}{extra}  {body.hex()}")
        p += 1 + ln
    if dtdoff < 4:                                     # d = 0: no DTDs and no data block collection
        return
    p, i = dtdoff, 0
    while p + 18 <= 127 and (blk[p] or blk[p + 1]):
        dtd(blk[p:p + 18], f"CTA DTD{i}"); p += 18; i += 1


def displayid_block(blk):
    ver, sz, prod, ext = blk[1], blk[2], blk[3], blk[4]
    print(f"  DisplayID {ver >> 4}.{ver & 0xF}  section size {sz}  product type {prod}  extensions {ext}")
    p, end = 5, min(5 + sz, 126)                       # byte 126 is the section checksum, 127 the block's
    while p + 3 <= end:
        dtag, drev, dlen = blk[p], blk[p + 1], blk[p + 2]
        if dtag == 0 and dlen == 0:                    # zero padding runs to the end of the section
            break
        body = blk[p + 3:min(p + 3 + dlen, end)]
        print(f"  data block tag=0x{dtag:02x} ({DID_BLOCKS.get(dtag, '?')}) rev=0x{drev:02x} len={dlen}")
        if dtag == 0x03:      # Type I: 20 bytes each, pclk in (value+1) x 10 kHz, sizes stored minus one
            for k in range(0, dlen, 20):
                e = body[k:k + 20]
                if len(e) < 20:
                    break
                pc = ((e[2] << 16 | e[1] << 8 | e[0]) + 1) * 10_000
                ha = (e[5] << 8 | e[4]) + 1; hb = (e[7] << 8 | e[6]) + 1
                va = (e[13] << 8 | e[12]) + 1; vb = (e[15] << 8 | e[14]) + 1
                ht, vt = ha + hb, va + vb
                hz = pc / (ht * vt) if ht and vt else 0
                pref = "  PREFERRED" if e[3] & 0x80 else ""
                print(f"    Type I: {ha}x{va} @{hz:8.3f}Hz  pclk {pc/1e6:8.2f}MHz  total {ht}x{vt}"
                      f"  hblank {hb} vblank {vb}  H {pc/ht/1000:.1f}kHz  vblank {vb*ht/pc*1e6:.1f}us{pref}")
        elif dtag == 0x22:    # Type VII: 20 bytes each, pclk in (value+1) kHz
            for k in range(0, dlen, 20):
                e = body[k:k + 20]
                if len(e) < 20:
                    break
                pc = (e[2] << 16 | e[1] << 8 | e[0]) + 1
                ha = (e[5] << 8 | e[4]) + 1; hb = (e[7] << 8 | e[6]) + 1
                va = (e[13] << 8 | e[12]) + 1; vb = (e[15] << 8 | e[14]) + 1
                ht, vt = ha + hb, va + vb
                hz = pc * 1000 / (ht * vt) if ht and vt else 0
                print(f"    Type VII: {ha}x{va} @{hz:8.3f}Hz  pclk {pc/1000:8.3f}MHz  total {ht}x{vt}")
        elif dtag == 0x23:
            print(f"    codes: {body.hex()}")
        else:
            print(f"    {body.hex()}")
        p += 3 + dlen


def dump(raw):
    nblocks = len(raw) // 128
    print(f"EDID {len(raw)} bytes = {nblocks} blocks\n")
    base_block(raw[:128], nblocks)
    for bi in range(1, nblocks):
        blk = raw[bi * 128:(bi + 1) * 128]
        tag = blk[0]
        print(f"\n=== block {bi}: tag=0x{tag:02x} "
              f"({'CTA-861' if tag == 0x02 else 'DisplayID' if tag == 0x70 else '?'})  ({checksum(blk)}) ===")
        if tag == 0x02:
            cta_block(blk)
        elif tag == 0x70:
            displayid_block(blk)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    try:
        raw = load_hex(argv[0])
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if len(raw) < 128 or len(raw) % 128:
        print(f"error: {len(raw)} bytes is not a whole number of 128-byte EDID blocks", file=sys.stderr)
        return 1
    dump(raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
