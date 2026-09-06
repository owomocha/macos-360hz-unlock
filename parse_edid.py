"""EDID を全ブロック解析する（base / CTA-861 / DisplayID）。高レート timing の在処を特定するのが目的。"""
import sys, struct

raw = bytes.fromhex(open(sys.argv[1]).read().strip())
print(f"EDID {len(raw)} バイト = {len(raw)//128} ブロック\n")

def dtd(b, label):
    pc = (b[1] << 8 | b[0]) * 10000  # 10kHz 単位
    if pc == 0:
        return None
    ha = b[2] | ((b[4] & 0xF0) << 4); hb = b[3] | ((b[4] & 0x0F) << 8)
    va = b[5] | ((b[7] & 0xF0) << 4); vb = b[6] | ((b[7] & 0x0F) << 8)
    hs = b[8] | ((b[11] & 0xC0) << 2); hw = b[9] | ((b[11] & 0x30) << 4)
    vs = (b[10] >> 4) | ((b[11] & 0x0C) << 2); vw = (b[10] & 0x0F) | ((b[11] & 0x03) << 4)
    ht, vt = ha + hb, va + vb
    hz = pc / (ht * vt) if ht and vt else 0
    intl = "i" if b[17] & 0x80 else "p"
    print(f"  [{label}] {ha}x{va}{intl} @{hz:7.3f}Hz  pclk {pc/1e6:7.3f}MHz  "
          f"total {ht}x{vt}  hblank {hb} vblank {vb}")
    return hz

print("=== Block 0: base EDID ===")
b0 = raw[:128]
print(f"  製造者 {chr(((b0[8]<<8|b0[9])>>10 & 31)+64)}{chr(((b0[8]<<8|b0[9])>>5 & 31)+64)}{chr(((b0[8]<<8|b0[9]) & 31)+64)}"
      f" product 0x{b0[11]<<8|b0[10]:04x}  EDID {b0[18]}.{b0[19]}  拡張ブロック数 {b0[126]}")
vid = b0[20]
print(f"  入力: {'デジタル' if vid & 0x80 else 'アナログ'} bitdepth={(vid>>4)&7} interface={vid&0xF} (5=DisplayPort, 2=HDMIa)")
for i in range(4):
    o = 54 + i * 18
    d = b0[o:o+18]
    if d[0] or d[1]:
        dtd(d, f"base DTD{i}")
    elif d[3] == 0xFC:
        print(f"  [name] {d[5:18].decode('ascii','replace').strip()}")
    elif d[3] == 0xFD:
        off = d[4]   # EDID 1.4 range-limit offset flags: bit0/1 = V min/max +255, bit2/3 = H min/max +255
        vmin = d[5] + (255 if off & 0x01 else 0); vmax = d[6] + (255 if off & 0x02 else 0)
        hmin = d[7] + (255 if off & 0x04 else 0); hmax = d[8] + (255 if off & 0x08 else 0)
        print(f"  [range] V {vmin}-{vmax}Hz  H {hmin}-{hmax}kHz  maxPclk {d[9]*10}MHz  offsets=0x{off:02x}")

for bi in range(1, len(raw)//128):
    blk = raw[bi*128:(bi+1)*128]
    tag = blk[0]
    print(f"\n=== Block {bi}: tag=0x{tag:02x} "
          f"({'CTA-861' if tag==0x02 else 'DisplayID' if tag==0x70 else '?'}) ===")
    if tag == 0x02:
        rev, dtdoff = blk[1], blk[2]
        print(f"  rev {rev}  DTD開始 0x{dtdoff:02x}  flags 0x{blk[3]:02x} (native DTD数 {blk[3]&0xF})")
        p = 4
        while p < dtdoff:
            t, ln = blk[p] >> 5, blk[p] & 0x1F
            body = blk[p+1:p+1+ln]
            names = {1:"Audio",2:"Video(VIC)",3:"Vendor",4:"SpeakerAlloc",7:"Extended"}
            extra = ""
            if t == 3 and len(body) >= 3:
                oui = body[2] << 16 | body[1] << 8 | body[0]
                extra = f" OUI=0x{oui:06x}" + (" [HDMI 1.4 VSDB]" if oui == 0x000c03
                        else " [HDMI 2.1 HF-VSDB]" if oui == 0xc45dd8 else "")
                if oui == 0xc45dd8 and len(body) >= 7:
                    extra += f" MaxFRL={body[6]>>4} (0=なし,1=3G3L,2=6G3L,3=6G4L,4=8G4L,5=10G4L,6=12G4L)"
                if oui == 0x000c03 and len(body) >= 7:
                    extra += f" MaxTMDS={body[6]*5}MHz"
            if t == 7 and body:
                ext = {0:"VideoCap",5:"ColorimetryData",6:"HDRstatic",0x0e:"YCbCr420",0x22:"VTDB(DisplayID)"}
                extra = f" ext=0x{body[0]:02x} {ext.get(body[0],'')}"
            print(f"  DataBlock t={t}({names.get(t,'?')}) len={ln}{extra}  {body.hex()}")
            p += 1 + ln
        p = dtdoff
        i = 0
        while p + 18 <= 127 and (blk[p] or blk[p+1]):
            dtd(blk[p:p+18], f"CTA DTD{i}"); p += 18; i += 1
    elif tag == 0x70:
        ver, sz, prod, ext = blk[1], blk[2], blk[3], blk[4]
        print(f"  DisplayID version 0x{ver:02x}  セクションサイズ {sz}  product type {prod}")
        p = 5
        end = 5 + sz
        while p < end and p < 127:
            dtag, drev, dlen = blk[p], blk[p+1], blk[p+2]
            body = blk[p+3:p+3+dlen]
            tags = {0x03:"Type I timing", 0x22:"Type VII timing (詳細)", 0x23:"Type VIII enumerated",
                    0x24:"Type IX formula", 0x2a:"Type X formula", 0x20:"Product ID",
                    0x21:"Display Params", 0x26:"Interface features", 0x32:"Vendor"}
            print(f"  DataBlock tag=0x{dtag:02x} ({tags.get(dtag,'?')}) rev=0x{drev:02x} len={dlen}")
            if dtag == 0x22:  # Type VII = 20 バイト/エントリ・pclk は 3 バイト
                for k in range(0, dlen, 20):
                    e = body[k:k+20]
                    if len(e) < 20: break
                    pc = (e[2] << 16 | e[1] << 8 | e[0]) + 1  # kHz 単位
                    ha = (e[5] << 8 | e[4]) + 1; hb = (e[7] << 8 | e[6]) + 1
                    va = (e[13] << 8 | e[12]) + 1; vb = (e[15] << 8 | e[14]) + 1
                    ht, vt = ha + hb, va + vb
                    hz = pc * 1000 / (ht * vt) if ht and vt else 0
                    print(f"    ★Type VII: {ha}x{va} @{hz:7.3f}Hz  pclk {pc/1000:8.3f}MHz  total {ht}x{vt}")
            elif dtag == 0x03:  # Type I = 20 バイト/エントリ・pclk は (値+1)×10kHz・寸法は (値+1)
                for k in range(0, dlen, 20):
                    e = body[k:k+20]
                    if len(e) < 20: break
                    pc = ((e[2] << 16 | e[1] << 8 | e[0]) + 1) * 10_000
                    ha = (e[5] << 8 | e[4]) + 1; hb = (e[7] << 8 | e[6]) + 1
                    va = (e[13] << 8 | e[12]) + 1; vb = (e[15] << 8 | e[14]) + 1
                    ht, vt = ha + hb, va + vb
                    hz = pc / (ht * vt) if ht and vt else 0
                    pref = " PREFERRED" if e[3] & 0x80 else ""
                    print(f"    ★Type I: {ha}x{va} @{hz:8.3f}Hz  pclk {pc/1e6:8.2f}MHz  total {ht}x{vt}"
                          f"  hblank {hb} vblank {vb}  H {pc/ht/1000:.1f}kHz{pref}")
            elif dtag == 0x23:  # Type VIII = enumerated (VIC/DMT コード列)
                print(f"    codes: {body.hex()}")
            else:
                print(f"    {body.hex()}")
            p += 3 + dlen
