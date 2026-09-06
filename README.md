# display360

[日本語](README.ja.md) · [![ci](https://github.com/owomocha/display360/actions/workflows/ci.yml/badge.svg)](https://github.com/owomocha/display360/actions)

My monitor does 360 Hz. macOS insisted on 300. This is how I got the last 60 Hz back without buying anything, and the tool that came out of it: give it your monitor's EDID and the refresh rate you want, and it makes the Mac accept a timing it would otherwise throw away.

Short version: the Mac's display coprocessor (the DCP) throws away the monitor's own 360 Hz timing. So I hand it a slightly edited EDID through a couple of private IOKit calls and make it rebuild its timing table. After that, 360 Hz is just another entry in System Settings. A tiny LaunchAgent re-does the trick whenever the monitor reconnects.

It works, and I mean actually measured, not "the menu says 360":

```
mode reported   : 360.0000 Hz
vsync counted   : 359.9977 Hz   (1801 frames in 5.000 s, CVDisplayLink callback)
frame interval  : median 2.7775 ms
```

Setup: MacBook Pro 16" M2 Pro (Mac14,10), macOS 26.5.2, Pixio PX259PS over USB-C (DP alt mode).

Fair warning: this pokes undocumented IOKit functions (`IOAVService*`, `IODP*`) and drives the panel a little outside its stock timing. It's been running on my machine since the end of August with no drama, but it's a hack. Read [Caveats](#caveats) before you run it.

## Scope

The name is only because my monitor went from 300 to 360. Nothing in the tool is specific to that: `build_edid.py` takes the resolution and rate you want, and the daemon takes them as arguments and reads the monitor's manufacturer/product ID from the EDID you give it, so it never touches a monitor the EDID wasn't made for.

What it still assumes:

- Apple Silicon (the DCP is where the timing table lives) and a DisplayPort link (USB-C alt mode or Thunderbolt). HDMI is untested.
- The monitor keeps its timings in a DisplayID Type I block. That's what `build_edid.py` rewrites. Type VII blocks and CTA DTDs aren't handled yet; open an issue with your EDID if that's what you have.
- macOS is rejecting the mode because of the blanking-time rule below. If the mode is missing because the link can't carry it (bandwidth, no DSC), no EDID trick will fix that.
- One monitor verified. Everything else is extrapolation from how the DCP behaved with that one, so if you try it on something else, I'd like to hear how it went.

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

You need an Apple Silicon Mac, Xcode command line tools (`clang`, `make`), and Python 3 with PyObjC's Quartz bindings for the switching and measuring scripts (`pip install pyobjc-framework-Quartz`). The generator and the parser are plain Python.

```sh
git clone https://github.com/owomocha/display360 && cd display360
make                                              # builds vedid

./vedid edid > edid/mine.hex                      # your monitor's stock EDID as one hex line (read-only)
python3 parse_edid.py edid/mine.hex               # what it advertises, and where the timing you want lives
python3 build_edid.py edid/mine.hex --rate 360    # -> edid/mine-360.hex, plus a table of the candidates
./enable.sh edid/mine-360.hex 1920 360            # inject, rebuild, switch, count vsyncs for 5 seconds
python3 check.py --rate 360                       # is a 360 Hz mode in the DCP's usable table? in CoreGraphics?
```

For another resolution or rate: `build_edid.py edid/mine.hex --rate 240 --width 2560 --height 1440`. The default candidates are the four blanking pairs that worked for me (`--blanking 200x80,216x90,160x80,160x64`, hblank x vblank; the first one becomes the preferred timing). The generator prints each candidate's vertical blanking time and flags anything under 155 µs, the lowest I've seen the DCP accept. The pixel-clock ceiling comes from your EDID's own range-limits descriptor (`--force` to ignore it).

`edid/pixio-px259ps.hex` is my PX259PS's stock EDID (no serial number in there, I checked) and `edid/pixio-px259ps-360.hex` is what the generator makes from it. Those are also the defaults of `enable.sh` and `install.sh`, so with the same monitor you can run them with no arguments.

To undo: pick the old rate in System Settings, `python3 setmode.py revert --rate 300`, or unplug the cable. The virtual EDID doesn't survive a replug, which is the whole reason the next section exists.

### Keeping it on

```sh
./install.sh edid/mine-360.hex 1920 360    # builds vedid if needed, writes ~/Library/LaunchAgents/com.local.display360.plist, starts it
./uninstall.sh                             # stops and removes it, no sudo
```

`vedid daemon <edid> <width> <rate>` sits on an IOKit matching notification for `DCPAVServiceProxy`, so it fires when a display connects: inject, rebuild, switch to the `<width>`-wide mode at `<rate>` Hz. It also wakes up every 30 seconds to check the mode still exists and re-injects only if it's gone (sleep/wake eats it). It deliberately won't fight you: if the mode is available and you picked another rate yourself, it leaves that alone until the next replug. And it compares the monitor's manufacturer/product ID with bytes 8 to 11 of the EDID it was given, so plugging in some other monitor does nothing.

Log is `display360.log` next to the binary; `launchctl print gui/$(id -u)/com.local.display360` for status.

## If your candidates don't show up

`python3 timings.py 100` prints the DCP's candidate table next to its usable table and marks each candidate `[usable]` or `[dropped]`. That's the fastest feedback loop I found. If everything is dropped, try fatter blanking (`--blanking 240x100,200x80`). If nothing even appears as a candidate, the injection didn't take: check `display360.log`, and read the hot-plug warning above.

## Caveats

- **Private APIs.** Everything under `IOAVService*` / `IODP*` is undocumented. Any macOS update can break it without a word. `cgs_modes.py` also uses the private `CGSGetDisplayModeDescriptionOfLength` to list hidden modes.
- **Slightly out of spec.** Candidate A runs my panel at 885.31 MHz pixel clock, 7.5 % above its own 360 Hz timing, and 417.6 kHz horizontal (+4.5 %). That's still inside the 900 MHz the EDID declares as its max, and mine has been fine, but if yours flickers, use a single conservative candidate (`--blanking 160x64`, which is D at 856.63 MHz).
- **Volatile.** Reboot, replug, sleep: all of them clear the virtual EDID. The login window (before your session) stays at the stock rate.
- **SIP.** I developed this with SIP off for unrelated reasons. It runs as a normal user there. I haven't tested it with SIP on; I'd expect the IOKit user clients to still be reachable, but that's a guess, not a fact.
- **If the screen goes black:** `./vedid hpd` forces a hot-plug on the external controller, which brings the display back with its wired EDID. Or unplug and replug. Nothing here touches the system outside the LaunchAgent plist in your home directory.

## Files

| | |
|---|---|
| `vedid.c` | the tool: EDID dump and injection, DP device/port calls, hot-plug, daemon |
| `build_edid.py` | the generator: rewrites the DisplayID Type I block, recomputes both checksums |
| `parse_edid.py` | decode every EDID block (base, CTA-861, DisplayID) |
| `enable.sh` | inject → rebuild → switch → measure |
| `setmode.py` | list or select the target mode and count real vsyncs; `revert` goes back |
| `check.py` | one-shot status; `--set` also switches and measures |
| `timings.py` | DCP candidate table vs usable table, side by side |
| `cgs_modes.py` | every display mode via the private CGS API, hidden ones included |
| `install.sh` / `uninstall.sh` | LaunchAgent on/off |
| `edid/` | my monitor's stock EDID and the generated one |
| `tests/` | the generator has to reproduce the shipped EDID byte for byte, plus the edge cases (`make test`) |

`vedid` subcommands: `info`, `edid`, `set <hex>`, `clear`, `devupd [n]`, `ports`, `pset <hex>`, `hpd`, `daemon <hex> [width] [rate]`. The source has a line on each.

CI builds the tool and runs the tests on a macOS runner. It can't exercise the injection itself; that takes a monitor on a real Mac.

## Things that bit me

- `TimingElements` entries nest `HorizontalAttributes` / `VerticalAttributes`. Grab the inner dict without looking and you'll read the horizontal frequency (kHz) as a vertical rate. I spent a while wondering what a 343 Hz mode was.
- `SyncRate` is rounded to 0.5 Hz steps. `PreciseSyncRate` has the real value. Both are in 1/65536 units.
- DisplayID Type I stores the pixel clock as `(value + 1) × 10 kHz`. My first generator forgot the +1 and every rate came out 0.01 MHz low. Not enough to break anything, enough to make the numbers not match and drive me nuts.
- EDID range limits have offset flags. Bit 1 adds 255 to the V max, which is how this panel says 48 to 360 Hz and not 48 to 105. Its H range field is broken (`255 to 255 kHz`), so don't use it for anything.
- `CVDisplayLinkGetActualOutputVideoRefreshPeriod` returns 0 until you install an output handler, and from Python the handler has to return a `(0, 0)` tuple or the process dies.

## License

MIT.
