"""DCP のタイミング表（候補 PreferredTimingElements / 使用可能 TimingElements）を対で正しく読む。

各要素は HorizontalAttributes / VerticalAttributes の入れ子。内側 dict だけを拾うと
水平周波数(kHz) を垂直レート(Hz) と取り違えるので注意。SyncRate はどちらも 1/65536 単位。

実行: python3 timings.py [最小Hz(既定100)]
"""
import re, subprocess, sys

MINHZ = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
io = subprocess.run(["ioreg", "-lw0"], capture_output=True, text=True).stdout


def span(s, i, o, c):
    d = 0
    for j in range(i, len(s)):
        if s[j] == o:
            d += 1
        elif s[j] == c:
            d -= 1
            if d == 0:
                return j
    return -1


def collect(key):
    res = {}
    for m in re.finditer(r'"%s" = \(' % key, io):
        i = m.end() - 1
        b = io[i + 1:span(io, i, "(", ")")]
        head = io.rfind("id 0x", 0, m.start())
        nid = io[head:head + 20].split(",")[0]
        elems, k = [], 0
        while k < len(b):
            if b[k] == "{":
                e = span(b, k, "{", "}")
                elems.append(b[k:e + 1])
                k = e + 1
            else:
                k += 1
        res.setdefault(nid, []).extend(elems)
    return res


def axis(e, name):
    m = re.search(r'"%sAttributes"=\{([^{}]*)\}' % name, e)
    return {k: int(v) for k, v in re.findall(r'"(\w+)"=(-?\d+)', m.group(1))}


def rate(d):
    """SyncRate は 0.5 刻みに丸められている。実値は PreciseSyncRate。"""
    return (d["PreciseSyncRate"] or d["SyncRate"]) / 65536.0


def row(e):
    h, v = axis(e, "Horizontal"), axis(e, "Vertical")
    hk = rate(h)                                       # 水平周波数 kHz
    return dict(vr=rate(v), w=h["Active"], ht=h["Total"], hk=hk,
                hh=v["Active"], vt=v["Total"],
                hb=h["Total"] - h["Active"], vb=v["Total"] - v["Active"],
                pclk=h["Total"] * hk / 1000.0,          # MHz
                score=int(re.search(r'"Score"=(\d+)', e).group(1)),
                unsafe=re.search(r'"UnsafeColorElementIDs"=\(([^)]*)\)', e).group(1))


TE, PE = collect("TimingElements"), collect("PreferredTimingElements")
for nid in TE:
    print(f"##### node {nid}   使用可能={len(TE[nid])}  候補={len(PE.get(nid, []))}")
    usable = {(r["ht"], r["vt"], round(r["vr"], 1)) for r in map(row, TE[nid])}
    for label, elems in (("候補 PreferredTimingElements", PE.get(nid, [])),
                         ("使用可能 TimingElements", TE[nid])):
        print(f"  --- {label}  (>= {MINHZ:g}Hz)")
        for r in sorted(map(row, elems), key=lambda r: -r["vr"]):
            if r["vr"] < MINHZ:
                continue
            mark = ""
            if label.startswith("候補"):
                mark = " ✅使用可能" if (r["ht"], r["vt"], round(r["vr"], 1)) in usable else " ❌除外"
            print(f"    {r['vr']:8.3f}Hz {r['w']}x{r['hh']} htot={r['ht']} vtot={r['vt']}"
                  f" hblank={r['hb']} vblank={r['vb']} H={r['hk']:.1f}kHz"
                  f" pclk={r['pclk']:.2f}MHz score={r['score']}"
                  f" unsafe=[{r['unsafe']}]{mark}")
    print()
