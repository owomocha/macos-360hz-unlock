"""360Hz タイミングを DisplayID Type I に注入した EDID を作る（仮想 EDID 用）。

真の受理条件は「ブランキングの行数」ではなく**時間**（採用側の最小 vblank 174.4µs /
除外側 75.1・90.9µs）。それを満たす候補を複数入れて、どれが通るかで規則も同時に確定させる。

pclk フィールドは (値+1)×10kHz。旧 build_edid.py は +1 を忘れていた。
"""
import pathlib, sys

HERE = pathlib.Path(__file__).parent
raw = bytearray(bytes.fromhex((HERE / "edid.hex").read_text().strip()))
assert len(raw) == 384
orig = bytes(raw)

def entry(pclk_hz, hact, hblank, hfp, hsw, vact, vblank, vfp, vsw,
          flags=0x04, hpol=0, vpol=1):
    """DisplayID 1.2 Type I 詳細タイミング 20 バイト。数値はすべて -1 して格納。"""
    v = round(pclk_hz / 10_000) - 1
    assert 0 <= v < (1 << 24)
    def le16(x, hi=0):
        x = (x - 1) | (hi << 15)
        return bytes([x & 0xFF, (x >> 8) & 0xFF])
    return (bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, flags])
            + le16(hact) + le16(hblank) + le16(hfp, hpol) + le16(hsw)
            + le16(vact) + le16(vblank) + le16(vfp, vpol) + le16(vsw))

def parse_did(did):
    """DisplayID セクションのデータブロックを (tag, rev, payload) に分解。"""
    size = did[2]
    out, i, end = [], 5, 5 + size
    while i < end and did[i] != 0:
        tag, rev, ln = did[i], did[i+1], did[i+2]
        out.append((tag, rev, bytes(did[i+3:i+3+ln])))
        i += 3 + ln
    return size, out

# ---- 候補タイミング（すべて 1920x1080・約 360Hz）----
# name, htotal, vtotal, 備考
CANDS = [
    ("A", 2120, 1160),   # vblank 191.6µs / hblank 0.226µs  … 両基準を満たす最小構成
    ("B", 2136, 1170),   # vblank 213.7µs / hblank 0.240µs  … 余裕最大（pclk も最大）
    ("C", 2080, 1160),   # vblank 191.6µs / hblank 0.184µs  … hblank 時間が効くかの判別用
    ("D", 2080, 1144),   # vblank 155.4µs / hblank 0.187µs  … vblank 閾値の下限探り(300Hzと同構造)
]
PREFERRED = "A"

did = bytearray(raw[256:384])
size, blocks = parse_did(did)
t1 = [b for b in blocks if b[0] == 0x03][0]
others = [b for b in blocks if b[0] != 0x03]

# 既存 2 本のうち 300Hz(先頭)だけ残す。純正 360Hz(2 本目)は macOS が必ず蹴るので捨てる。
keep = t1[2][:20]
print("=== 残す既存タイミング ===")
print(f"  300Hz  htotal 2080 / vtotal 1144  (先頭 20 バイト = {keep[:4].hex()}…)")

print("\n=== 追加する 360Hz 候補 ===")
print(f"{'':2} {'htotal':>7} {'vtotal':>7} {'hbl':>4} {'vbl':>4} {'pclk MHz':>9} "
      f"{'H kHz':>8} {'Hz':>9} {'vblank µs':>10} {'hblank µs':>10} {'Gbps':>6}")
new = b""
for name, ht, vt in CANDS:
    pclk = round(ht * vt * 360 / 10_000) * 10_000      # 10kHz 単位に丸める
    hb, vb = ht - 1920, vt - 1080
    hz = pclk / (ht * vt); hk = pclk / ht
    flags = 0x84 if name == PREFERRED else 0x04
    new += entry(pclk, 1920, hb, 48, 64, 1080, vb, 3, 5, flags=flags)
    print(f"{name:2} {ht:>7} {vt:>7} {hb:>4} {vb:>4} {pclk/1e6:>9.2f} {hk/1000:>8.1f} "
          f"{hz:>9.4f} {vb/hk*1e6:>10.1f} {hb/pclk*1e6:>10.3f} {pclk*24/1e9:>6.2f}"
          + ("   ← preferred" if name == PREFERRED else ""))
    assert pclk <= 900_000_000, f"{name}: pclk が EDID 申告上限 900MHz 超"

body = keep + new
newblocks = bytes([0x03, t1[1], len(body)]) + body
for tag, rev, pl in others:
    newblocks += bytes([tag, rev, len(pl)]) + pl
assert len(newblocks) <= size, f"DisplayID に入りきらない: {len(newblocks)} > {size}"

did[5:5+size] = newblocks + b"\x00" * (size - len(newblocks))
did[126] = 0
did[126] = (256 - sum(did[1:5+size]) % 256) % 256     # DisplayID チェックサム
did[127] = 0
did[127] = (256 - sum(did) % 256) % 256               # EDID 拡張ブロックチェックサム
raw[256:384] = did

for b in range(3):
    assert sum(raw[b*128:(b+1)*128]) % 256 == 0, f"block{b} チェックサム不一致"
assert sum(did[1:127]) % 256 == 0, "DisplayID チェックサム不一致"
out = HERE / "edid_v2.hex"
out.write_text(raw.hex())
diff = [i for i in range(384) if raw[i] != orig[i]]
print(f"\n全チェックサム OK  →  {out}")
print(f"変更バイト数 {len(diff)}（すべて block2 内: {min(diff)}〜{max(diff)}）"
      f"  block0/1 は無改変={raw[:256]==orig[:256]}")
