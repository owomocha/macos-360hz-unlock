# display360

My monitor does 360 Hz. macOS insisted on 300. This is how I got the last 60 Hz back without buying anything.

Short version: the Mac's display coprocessor (the DCP) throws away the monitor's own 360 Hz timing. So I hand it a slightly edited EDID through a couple of private IOKit calls and make it rebuild its timing table. After that, 360 Hz is just another entry in System Settings. A tiny LaunchAgent re-does the trick whenever the monitor reconnects.

It works, and I mean actually measured, not "the menu says 360":

```
mode reported   : 360.0000 Hz
vsync counted   : 359.9977 Hz   (1801 frames in 5.000 s, CVDisplayLink callback)
frame interval  : median 2.7775 ms
```

Setup: MacBook Pro 16" M2 Pro (Mac14,10), macOS 26.5.2, Pixio PX259PS over USB-C (DP alt mode). Different monitor? See [Other monitors](#other-monitors). It's mostly "regenerate the EDID and change one constant", but you'll be doing your own homework on the timing.

Fair warning: this pokes undocumented IOKit functions (`IOAVService*`, `IODP*`) and drives the panel a little outside its stock timing. It's been running on my machine since the end of August with no drama, but it's a hack. Read [Caveats](#caveats) before you run it.

## What's actually going on

The PX259PS advertises 1920x1080 @ 360 Hz right in its EDID (a DisplayID Type I block). You can even watch the DCP consider it: it sits in `PreferredTimingElements` with the highest score of anything in the list (16846, vs 15922 for 300 Hz) and an empty `UnsafeColorElementIDs`. And then it's simply not in `TimingElements`, the table macOS actually uses. No public API lets you add a mode the DCP has dropped, and the old `/Library/Displays/.../DisplayProductID-xxxx` override trick doesn't reach the DCP at all anymore. All it did on my system was rename the display.

So the question became: why does it drop that one timing, and can I feed it one it won't?

## Why it gets dropped

I dumped every timing the DCP accepted (16 of them) and the two it rejected, and went looking for the rule. First guess: a minimum number of blanking lines. Wrong. 640x480@60 gets through with a 20-line vblank, 4096x2160@60 gets through with an 80-pixel hblank. Bandwidth or pixel clock? Also no. A 441 MHz mode is rejected while 571 MHz is fine.

What separates them cleanly is blanking *time*:

| | vblank | hblank | pclk |
|---|---:|---:|---:|
| smallest accepted timing | **174.4 µs** | 0.224 µs | 713.86 MHz |
| native 360 Hz (rejected) | **75.1 µs** | 0.170 µs | 823.17 MHz |
| native 200 Hz (rejected) | **90.9 µs** | 0.182 µs | 440.00 MHz |

Every accepted mode has a vblank above about 174 µs. Both rejected ones are way below. The monitor's stock 360 Hz timing is just too tight for the DCP's taste. So I built an EDID that keeps blocks 0 and 1 byte for byte, keeps the stock 300 Hz entry, and adds four 360 Hz candidates with fatter blanking:

| | htotal | vtotal | hblank | vblank | pclk | vblank time | |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 2120 | 1160 | 200 | 80 | 885.31 MHz | 191.6 µs | accepted, preferred |
| B | 2136 | 1170 | 216 | 90 | 899.68 MHz | 213.7 µs | not listed |
| C | 2080 | 1160 | 160 | 80 | 868.61 MHz | 191.6 µs | not listed |
| D | 2080 | 1144 | 160 | 64 | 856.63 MHz | 155.4 µs | accepted |

A and D showed up. I don't think B and C were rejected by the rule: A/B and C/D round to the same refresh rate (359.999 and 360.001 Hz), and it looks like duplicates get collapsed. If you want to know for sure, nudge the rates apart and try again; I stopped once A worked. D is the interesting one, because its 155 µs vblank is *below* the 174 µs floor I'd measured, so the real threshold is somewhere between 91 and 155 µs. Good enough for me.

A is what I run: `1920x1080, htotal 2120 / vtotal 1160, pclk 885.31 MHz, H 417.6 kHz`.

## The two calls that matter

```c
IOAVServiceSetVirtualEDIDMode(av, 1, edid);   // give the DCP a replacement EDID     (user client selector 23)
IODPDeviceSetUpdated(dp, 1);                  // make it re-parse and rebuild timings (selector 5)
```

The first one alone looks like it worked and does nothing. `IOAVServiceCopyEDID` happily returns your bytes, but the timing table was built at connect time and nobody rebuilds it. That's the second call's job.

What you should *not* do is `IOAVControllerForceHotPlugDetect`. It looks like the obvious "re-read the EDID" button, and it does re-read the EDID... the wired one, because the hot-plug tears down the whole AV service and your virtual EDID goes with it. I did this twice, watched the screen go black twice, and then went looking for something gentler. `IODPPortSetVirtualEDID` (the port-side version, which survives disconnects) didn't do anything by itself either; I think the port has to be flipped to virtual with `IODPPortSetVirtual` first, but I never needed it once `IODPDeviceSetUpdated` worked.

None of these have headers, so the signatures come from disassembling the implementations in the dyld shared cache:

| function | arguments | selector |
|---|---|---|
| `IOAVServiceSetVirtualEDIDMode` | `(IOAVServiceRef, uint32_t mode, CFDataRef edid)` | 23 |
| `IODPDeviceSetUpdated` | `(IODPDeviceRef, uint32_t)` | 5 |
| `IOAVServiceReadI2C` / `WriteI2C` | `(ref, chip, offset, buf, len)` | 24 / 25 |
| `IODPPortSetVirtual` | `(IODPPortRef, uint32_t)` | 0 |
| `IODPPortSetVirtualEDID` | `(IODPPortRef, CFDataRef)` | 4 |
| `IODPPortGetAddress` | `(ref, uint32_t*, uint32_t*, uint32_t*)` | |

That last one takes three out-pointers. I called it with one at first. Instant segfault, no message, very educational.

## Using it

You need an Apple Silicon Mac, `clang` (Xcode command line tools), and Python 3 with PyObjC's Quartz bindings for the helper scripts (`pip install pyobjc-framework-Quartz`).

```sh
git clone https://github.com/owomocha/display360 && cd display360
clang -O2 -o vedid vedid.c -framework IOKit -framework CoreFoundation -framework CoreGraphics

./vedid info              # dumps the wired EDID and the AV service properties, read-only
python3 build_edid2.py    # edid.hex (stock) -> edid_v2.hex (stock + the four candidates)
./enable360.sh            # inject, rebuild, switch to 360, count vsyncs for 5 seconds
python3 check.py          # is 360 in the DCP's usable table? in CoreGraphics? right now
```

`edid.hex` is my PX259PS's stock EDID (no serial number in there, I checked) and `edid_v2.hex` is the generated one, so if you have the same monitor you can go straight to `enable360.sh`.

To undo: pick 300 Hz in System Settings, or `python3 set360.py revert`, or unplug the cable. The virtual EDID doesn't survive a replug, which is the whole reason the next section exists.

### Keeping it on

```sh
./install.sh      # builds vedid if needed, writes ~/Library/LaunchAgents/com.local.display360.plist, starts it
./uninstall.sh    # stops and removes it, no sudo
```

`vedid daemon` sits on an IOKit matching notification for `DCPAVServiceProxy`, so it fires when a display connects: inject, rebuild, switch. It also wakes up every 30 seconds to check the 360 Hz mode still exists and re-injects only if it's gone (sleep/wake eats it). It deliberately won't fight you: if 360 is available and you picked 300 yourself, it leaves that alone until the next replug. And it checks the EDID manufacturer/product ID (`430f/0025`) first, so plugging in some other monitor does nothing.

Log is `display360.log` next to the binary; `launchctl print gui/$(id -u)/com.local.display360` for status.

The tools print in Japanese at the moment. I'll get to an English pass.

## Other monitors

1. `./vedid info`, save the EDID dump as `edid.hex`.
2. `python3 parse_edid.py edid.hex` to see what it advertises and where the timing lives (DisplayID Type I / Type VII, CTA DTD). `build_edid2.py` assumes a DisplayID Type I block; edit `CANDS` for your resolution and rate, and keep the vblank comfortably above 155 µs (175+ is known good).
3. Change `PIXIO_ID` in `vedid.c` (EDID bytes 8 to 11) and the mode filter in `find_target` (currently width 1920, rate > 355). Rebuild.
4. `python3 timings.py 100` prints the DCP's candidate table next to its usable table and marks which of your candidates made it. Fastest feedback loop I found.

If your monitor's high-rate timing is in a Type VII block or a CTA DTD instead, the generator needs a bit of work. PRs welcome, or open an issue with your EDID and I'll take a look.

## Caveats

- **Private APIs.** Everything under `IOAVService*` / `IODP*` is undocumented. Any macOS update can break it without a word. `cgs_modes.py` also uses the private `CGSGetDisplayModeDescriptionOfLength` to list hidden modes.
- **Slightly out of spec.** Candidate A runs the panel at 885.31 MHz pixel clock, 7.5 % above its own 360 Hz timing, and 417.6 kHz horizontal (+4.5 %). That's still inside the 900 MHz the EDID declares as its max, and mine has been fine, but if yours flickers, keep only D (856.63 MHz) in `CANDS`.
- **Volatile.** Reboot, replug, sleep: all of them clear the virtual EDID. The login window (before your session) stays at 300.
- **SIP.** I developed this with SIP off for unrelated reasons. It runs as a normal user there. I haven't tested it with SIP on; I'd expect the IOKit user clients to still be reachable, but that's a guess, not a fact.
- **If the screen goes black:** `./vedid hpd` forces a hot-plug on the external controller, which brings the display back with its wired EDID. Or unplug and replug. Nothing here touches the system outside the LaunchAgent plist in your home directory.

## Files

| | |
|---|---|
| `vedid.c` | the tool: EDID injection, DP device/port calls, hot-plug, daemon |
| `edid.hex` | stock PX259PS EDID (the generator reads it, keep it) |
| `edid_v2.hex` | generated EDID with the four candidates, blocks 0/1 untouched |
| `build_edid2.py` | the generator: rewrites the DisplayID Type I block, redoes both checksums |
| `enable360.sh` | inject → rebuild → switch → measure |
| `set360.py` | list/select a 360 mode and count real vsyncs; `revert` goes back to 300 |
| `check.py` | one-shot status; `--set` also switches and measures |
| `timings.py` | DCP candidate table vs usable table, side by side |
| `parse_edid.py` | decode all EDID blocks (base, CTA-861, DisplayID) |
| `cgs_modes.py` | every display mode via the private CGS API, hidden ones included |
| `install.sh` / `uninstall.sh` | LaunchAgent on/off |

`vedid` subcommands: `info`, `set <hex>`, `clear`, `devupd [n]`, `ports`, `pset <hex>`, `hpd`, `daemon [hex]`. The source has a line on each.

## Things that bit me

- `TimingElements` entries nest `HorizontalAttributes` / `VerticalAttributes`. Grab the inner dict without looking and you'll read the horizontal frequency (kHz) as a vertical rate. I spent a while wondering what a 343 Hz mode was.
- `SyncRate` is rounded to 0.5 Hz steps. `PreciseSyncRate` has the real value. Both are in 1/65536 units.
- DisplayID Type I stores the pixel clock as `(value + 1) × 10 kHz`. My first generator forgot the +1 and every rate came out 0.01 MHz low. Not enough to break anything, enough to make the numbers not match and drive me nuts.
- EDID range limits have offset flags. Bit 1 adds 255 to the V max, which is how this panel says 48 to 360 Hz and not 48 to 105. Its H range field is broken (`255 to 255 kHz`), so don't use it for anything.
- `CVDisplayLinkGetActualOutputVideoRefreshPeriod` returns 0 until you install an output handler, and from Python the handler has to return a `(0, 0)` tuple or the process dies.

## License

MIT. There's a longer Japanese write-up of the investigation in [README.ja.md](README.ja.md).
