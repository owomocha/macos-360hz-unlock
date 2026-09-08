#!/usr/bin/env python3
"""Print the DCP's timing tables side by side: the candidates it considered
(PreferredTimingElements) and the ones it actually uses (TimingElements).
The fastest way to see whether a candidate you injected got accepted.

    timings.py [min_hz]        hide entries slower than min_hz (default 100)

Each element nests HorizontalAttributes / VerticalAttributes; read only the inner
dict and you will mistake the horizontal frequency (kHz) for the vertical rate.
SyncRate is rounded to 0.5 Hz steps, PreciseSyncRate is the real value (both in
1/65536 units).
"""
import re
import subprocess
import sys


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


def collect(io, key):
    """{registry node id: [element text, ...]} for every `key` = ( ... ) array in the ioreg dump."""
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
    return {k: int(v) for k, v in re.findall(r'"(\w+)"=(-?\d+)', m.group(1))} if m else None


def rate(d):
    return (d.get("PreciseSyncRate") or d["SyncRate"]) / 65536.0


def row(e):
    """One timing element as numbers, or None if it has no H/V attributes."""
    h, v = axis(e, "Horizontal"), axis(e, "Vertical")
    if not h or not v:
        return None
    hk = rate(h)                                       # horizontal frequency, kHz
    score = re.search(r'"Score"=(\d+)', e)
    unsafe = re.search(r'"UnsafeColorElementIDs"=\(([^)]*)\)', e)
    return dict(vr=rate(v), w=h["Active"], ht=h["Total"], hk=hk,
                hh=v["Active"], vt=v["Total"],
                hb=h["Total"] - h["Active"], vb=v["Total"] - v["Active"],
                pclk=h["Total"] * hk / 1000.0,          # MHz
                score=int(score.group(1)) if score else -1,
                unsafe=unsafe.group(1) if unsafe else "")


def rows(elems):
    return [r for r in map(row, elems) if r]


def report(io, minhz=100.0, out=sys.stdout):
    te, pe = collect(io, "TimingElements"), collect(io, "PreferredTimingElements")
    for nid in te:
        print(f"##### node {nid}   usable={len(te[nid])}  candidates={len(pe.get(nid, []))}", file=out)
        usable = {(r["ht"], r["vt"], round(r["vr"], 1)) for r in rows(te[nid])}
        for label, elems in (("candidates (PreferredTimingElements)", pe.get(nid, [])),
                             ("usable (TimingElements)", te[nid])):
            print(f"  --- {label}  (>= {minhz:g} Hz)", file=out)
            for r in sorted(rows(elems), key=lambda r: -r["vr"]):
                if r["vr"] < minhz:
                    continue
                mark = ""
                if label.startswith("candidates"):
                    mark = "  [usable]" if (r["ht"], r["vt"], round(r["vr"], 1)) in usable else "  [dropped]"
                print(f"    {r['vr']:8.3f}Hz {r['w']}x{r['hh']} htot={r['ht']} vtot={r['vt']}"
                      f" hblank={r['hb']} vblank={r['vb']} H={r['hk']:.1f}kHz"
                      f" pclk={r['pclk']:.2f}MHz score={r['score']}"
                      f" unsafe=[{r['unsafe']}]{mark}", file=out)
        print(file=out)
    if not te:
        print("no TimingElements in the registry: is an external display connected?", file=out)
    return 0 if te else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        minhz = float(argv[0]) if argv else 100.0
    except ValueError:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    io = subprocess.run(["ioreg", "-lw0"], capture_output=True, text=True).stdout
    return report(io, minhz)


if __name__ == "__main__":
    sys.exit(main())
