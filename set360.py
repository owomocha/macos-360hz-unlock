"""360Hz モードへ切り替えて vsync を実計数する。

使い方:
  set360.py            … 候補一覧を出すだけ（切り替えない）
  set360.py <index>    … その候補に切り替えて 5 秒実測
  set360.py revert     … 300Hz に戻す
"""
import sys, time
import Quartz

def modes(did):
    return Quartz.CGDisplayCopyAllDisplayModes(
        did, {"kCGDisplayShowDuplicateLowResolutionModes": True}) or []

err, ids, cnt = Quartz.CGGetOnlineDisplayList(16, None, None)
did = None
for d in ids:
    if any(Quartz.CGDisplayModeGetRefreshRate(m) > 355 for m in modes(d)):
        did = d
if did is None:
    print("360Hz 候補を持つディスプレイが無い"); raise SystemExit(1)

cands = [m for m in modes(did)
         if Quartz.CGDisplayModeGetRefreshRate(m) > 355
         and Quartz.CGDisplayModeGetWidth(m) == 1920
         and Quartz.CGDisplayModeIsUsableForDesktopGUI(m)]
arg = sys.argv[1] if len(sys.argv) > 1 else None

if arg == "revert":
    for m in modes(did):
        if (abs(Quartz.CGDisplayModeGetRefreshRate(m) - 300) < 0.5
                and Quartz.CGDisplayModeGetWidth(m) == 1920
                and Quartz.CGDisplayModeGetPixelWidth(m) == 1920
                and Quartz.CGDisplayModeIsUsableForDesktopGUI(m)):
            err, cfg = Quartz.CGBeginDisplayConfiguration(None)
            Quartz.CGConfigureDisplayWithDisplayMode(cfg, did, m, None)
            print("300Hz へ復帰 rc=", Quartz.CGCompleteDisplayConfiguration(cfg, 1))
            raise SystemExit(0)
    print("300Hz モードが見つからない"); raise SystemExit(1)

print(f"display 0x{did:x}  360Hz 候補 {len(cands)} 件:")
for i, m in enumerate(cands):
    print(f"  [{i}] {Quartz.CGDisplayModeGetWidth(m)}x{Quartz.CGDisplayModeGetHeight(m)}"
          f" @{Quartz.CGDisplayModeGetRefreshRate(m):.4f}Hz"
          f"  pixel {Quartz.CGDisplayModeGetPixelWidth(m)}x{Quartz.CGDisplayModeGetPixelHeight(m)}"
          f"  ioModeID={Quartz.CGDisplayModeGetIODisplayModeID(m)}")
if arg is None:
    print("\n切り替えるには: set360.py <index>")
    raise SystemExit(0)

m = cands[int(arg)]
err, cfg = Quartz.CGBeginDisplayConfiguration(None)
Quartz.CGConfigureDisplayWithDisplayMode(cfg, did, m, None)
rc = Quartz.CGCompleteDisplayConfiguration(cfg, 1)   # ForSession＝再起動で戻る安全側
print(f"\n切替 rc={rc}")
time.sleep(3)

err, link = Quartz.CVDisplayLinkCreateWithCGDisplay(did, None)
nom = Quartz.CVDisplayLinkGetNominalOutputVideoRefreshPeriod(link)
ts = []
def handler(dl, now, out, fin, fout):
    ts.append(time.monotonic()); return (0, 0)
Quartz.CVDisplayLinkSetOutputHandler(link, handler)
Quartz.CVDisplayLinkStart(link)
time.sleep(5)
act = Quartz.CVDisplayLinkGetActualOutputVideoRefreshPeriod(link)
Quartz.CVDisplayLinkStop(link)
cur = Quartz.CGDisplayCopyDisplayMode(did)
print(f"  ① モード申告  : {Quartz.CGDisplayModeGetRefreshRate(cur):.4f} Hz")
if nom.timeValue:
    print(f"  ② 公称周期    : {nom.timeScale/nom.timeValue:.4f} Hz")
if len(ts) > 10:
    span = ts[-1] - ts[0]
    d = sorted(ts[i+1]-ts[i] for i in range(len(ts)-1))
    print(f"  ③ vsync 実計数: {(len(ts)-1)/span:.4f} Hz  ({len(ts)} 回 / {span:.3f}s) ← 実出力")
    print(f"     フレーム間隔 中央値 {d[len(d)//2]*1000:.4f} ms")
print(f"  ④ CoreVideo実測: {1/act if act else 0:.4f} Hz")
