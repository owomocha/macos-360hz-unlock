"""360Hz が有効になっているかを 1 コマンドで確かめる。

実行: python3 check.py          （PyObjC の Quartz が要る: pip install pyobjc-framework-Quartz）
      （--set を付けると 360Hz が在れば切り替えて実測まで行う）

通常は LaunchAgent (com.local.display360) が自動で 360Hz にする。
✗ が出たら ./enable360.sh を叩けば手動で適用できる。
"""
import subprocess, sys, time
import Quartz

SET = "--set" in sys.argv

# 1) override が読まれているか（表示名で判定）
sp = subprocess.run(["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True).stdout
override_read = "(360Hz)" in sp
print(f"① EDID override が読まれている : {'はい' if override_read else 'いいえ'}"
      f"  （表示名に (360Hz) が付くか）")

# 2) DCP の使用可能タイミングに 360Hz が入ったか
ioreg = subprocess.run(["ioreg", "-lw0"], capture_output=True, text=True).stdout
import re
usable_360 = False
for m in re.finditer(r'"TimingElements" = \(', ioreg):
    i = m.end() - 1; d = 0; j = i
    while j < len(ioreg):
        if ioreg[j] == "(": d += 1
        elif ioreg[j] == ")":
            d -= 1
            if d == 0: break
        j += 1
    if '"SyncRate"=23592960' in ioreg[i:j]:      # 360*65536
        usable_360 = True
print(f"② DCP の使用可能表に 360Hz    : {'はい ★' if usable_360 else 'いいえ'}")

# 3) CoreGraphics のモード一覧
err, ids, cnt = Quartz.CGGetOnlineDisplayList(16, None, None)
target = None
for did in ids:
    modes = Quartz.CGDisplayCopyAllDisplayModes(
        did, {"kCGDisplayShowDuplicateLowResolutionModes": True}) or []
    rates = sorted({round(Quartz.CGDisplayModeGetRefreshRate(m), 2) for m in modes}, reverse=True)
    cur = Quartz.CGDisplayCopyDisplayMode(did)
    w, h = Quartz.CGDisplayModeGetWidth(cur), Quartz.CGDisplayModeGetHeight(cur)
    print(f"\ndisplay 0x{did:x}: 現在 {w}x{h} @{Quartz.CGDisplayModeGetRefreshRate(cur):.2f}Hz")
    print(f"  選べるレート: {rates}")
    for m in modes:
        if (Quartz.CGDisplayModeGetRefreshRate(m) > 355
                and Quartz.CGDisplayModeGetWidth(m) == 1920
                and Quartz.CGDisplayModeIsUsableForDesktopGUI(m)):
            target = (did, m)

print("\n" + "=" * 62)
if target is None:
    print("判定: ✗ 360Hz モードが無い（仮想 EDID がまだ入っていない）。")
    print("      → 手動適用: ./enable360.sh")
    print("      → 常駐の稼働確認: launchctl print gui/$(id -u)/com.local.display360")
    print("      → ログ: ./display360.log")
    raise SystemExit(1)

did, m = target
print(f"判定: ★ 360Hz モードが出現した！ "
      f"{Quartz.CGDisplayModeGetWidth(m)}x{Quartz.CGDisplayModeGetHeight(m)} "
      f"@{Quartz.CGDisplayModeGetRefreshRate(m):.3f}Hz (display 0x{did:x})")
if not SET:
    print("切り替えて実測するには: python3 check.py --set")
    raise SystemExit(0)

cur = Quartz.CGDisplayCopyDisplayMode(did)
err, cfg = Quartz.CGBeginDisplayConfiguration(None)
Quartz.CGConfigureDisplayWithDisplayMode(cfg, did, m, None)
rc = Quartz.CGCompleteDisplayConfiguration(cfg, 1)   # ForSession＝再起動で元に戻る安全側
print(f"\n切替 rc={rc}")
time.sleep(3)

err, link = Quartz.CVDisplayLinkCreateWithCGDisplay(did, None)
nom = Quartz.CVDisplayLinkGetNominalOutputVideoRefreshPeriod(link)
ts = []
def handler(dl, now, out, fin, fout):
    ts.append(time.monotonic())
    return (0, 0)
Quartz.CVDisplayLinkSetOutputHandler(link, handler)
Quartz.CVDisplayLinkStart(link)
time.sleep(5)
act = Quartz.CVDisplayLinkGetActualOutputVideoRefreshPeriod(link)
Quartz.CVDisplayLinkStop(link)
now = Quartz.CGDisplayCopyDisplayMode(did)
print(f"  ① モード申告  : {Quartz.CGDisplayModeGetRefreshRate(now):.4f} Hz")
if nom.timeValue:
    print(f"  ② 公称周期    : {nom.timeScale/nom.timeValue:.4f} Hz")
if len(ts) > 10:
    span = ts[-1] - ts[0]
    print(f"  ③ vsync 実計数: {(len(ts)-1)/span:.4f} Hz  ({len(ts)} 回 / {span:.3f}s) ← 実出力")
print(f"  ④ CoreVideo実測: {1/act if act else 0:.4f} Hz")
print("\nモニタの OSD でも入力リフレッシュレートを確認してください（これが最終的な地上検証）。")
print("元に戻すには再起動するか、System Settings > ディスプレイ で 300Hz を選択。")
