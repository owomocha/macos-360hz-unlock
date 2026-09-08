# display360

[日本語](README.ja.md) · [![ci](https://github.com/owomocha/display360/actions/workflows/ci.yml/badge.svg)](https://github.com/owomocha/display360/actions)

My monitor does 360 Hz. macOS insisted on 300. This is how I got the last 60 Hz back without buying anything: hand the Mac a slightly edited EDID through a couple of private IOKit calls and make its display coprocessor rebuild the timing table it had thrown that mode out of. You give the tool your EDID and a target rate; a small LaunchAgent redoes it on every reconnect.

Measured, not "the menu says 360":

```
mode reported   : 360.0000 Hz
vsync counted   : 359.9977 Hz   (1801 frames in 5.000 s, CVDisplayLink callback)
frame interval  : median 2.7775 ms
```

MacBook Pro 16" M2 Pro (Mac14,10), macOS 26.5.2, Pixio PX259PS over USB-C (DP alt mode). It pokes undocumented `IOAVService*` / `IODP*` and runs the panel a hair outside its stock timing — fine here since late August, but read the caveats first.

Nothing is 360-specific. `build_edid.py` and the daemon take the resolution and rate as arguments and match the monitor by the manufacturer/product ID in its EDID, so they won't touch a display the EDID wasn't made for. Assumptions: Apple silicon (the DCP owns the timing table) over DisplayPort; a monitor that keeps its timings in a DisplayID Type I block (Type VII and CTA DTDs aren't handled yet); and a mode macOS drops for the blanking rule below, not one the link physically can't carry. Verified on exactly one monitor — the rest is extrapolation from how that one's DCP behaved.

## why the DCP drops the mode

The PX259PS advertises 1920x1080 @ 360 Hz right in its EDID, and you can watch the DCP weigh it: top score in `PreferredTimingElements` (16846 vs 15922 for 300 Hz), empty `UnsafeColorElementIDs` — then absent from `TimingElements`, the table macOS actually uses. No public API adds back a mode the DCP dropped, and the old `DisplayProductID-xxxx` override never reaches the DCP anymore (on my system it just renamed the display).

So I dumped all 16 accepted timings and the 2 rejected ones and went looking for the rule. Not a minimum blanking-line count — 640x480@60 passes with a 20-line vblank. Not bandwidth or pixel clock — 441 MHz rejected, 571 MHz fine. What splits them cleanly is blanking *time*:

| | vblank | hblank | pclk |
|---|---:|---:|---:|
| smallest accepted timing | **174.4 µs** | 0.224 µs | 713.86 MHz |
| native 360 Hz (rejected) | **75.1 µs** | 0.170 µs | 823.17 MHz |
| native 200 Hz (rejected) | **90.9 µs** | 0.182 µs | 440.00 MHz |

Accepted modes sit above ~174 µs vblank; both rejects are well below. The stock 360 Hz timing is simply too tight for the DCP. So the generated EDID keeps blocks 0 and 1 byte-for-byte, keeps the 300 Hz entry, and adds four 360 Hz candidates with fatter blanking:

| | htotal | vtotal | hblank | vblank | pclk | vblank time | |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 2120 | 1160 | 200 | 80 | 885.31 MHz | 191.6 µs | accepted, preferred |
| B | 2136 | 1170 | 216 | 90 | 899.68 MHz | 213.7 µs | not listed |
| C | 2080 | 1160 | 160 | 80 | 868.61 MHz | 191.6 µs | not listed |
| D | 2080 | 1144 | 160 | 64 | 856.63 MHz | 155.4 µs | accepted |

A and D show up. A and B both round to 359.999 Hz and C and D to 360.001, so B and C look collapsed as duplicates rather than rejected. D is the tell: its 155 µs vblank is below the 174 µs floor I first measured, so the real threshold is somewhere between 91 and 155 µs. I run A: `1920x1080, htotal 2120 / vtotal 1160, pclk 885.31 MHz, H 417.6 kHz`.

Reading these numbers has its own traps. `SyncRate` is rounded to 0.5 Hz steps — the real value is in `PreciseSyncRate`, both in 1/65536 units. DisplayID Type I stores the pixel clock as `(value + 1) × 10 kHz`; miss the +1 and every rate comes out 0.01 MHz low. And the range-limits descriptor has offset flags — bit 1 adds 255 to the V-max, which is how this panel declares 48–360 Hz and not 48–105 (its H-range field is broken, `255 to 255 kHz`, so ignore it).

## the two calls that matter

```c
IOAVServiceSetVirtualEDIDMode(av, 1, edid);   // hand the DCP a replacement EDID      (selector 23)
IODPDeviceSetUpdated(dp, 1);                  // make it re-parse and rebuild timings  (selector 5)
```

The first alone looks like it worked and does nothing: `IOAVServiceCopyEDID` returns your bytes, but the timing table was built at connect time and nobody rebuilds it. That's the second call's job. What you must *not* reach for is `IOAVControllerForceHotPlugDetect` — it does re-read an EDID, the wired one, because the hot-plug tears down the whole AV service and your virtual EDID goes with it (two black screens before I gave up on it). None of these are in any header, so the signatures come from disassembling the implementations in the dyld shared cache:

| function | arguments | selector |
|---|---|---|
| `IOAVServiceSetVirtualEDIDMode` | `(IOAVServiceRef, uint32_t mode, CFDataRef edid)` | 23 |
| `IODPDeviceSetUpdated` | `(IODPDeviceRef, uint32_t)` | 5 |
| `IOAVServiceReadI2C` / `WriteI2C` | `(ref, chip, offset, buf, len)` | 24 / 25 |
| `IODPPortSetVirtual` | `(IODPPortRef, uint32_t)` | 0 |
| `IODPPortSetVirtualEDID` | `(IODPPortRef, CFDataRef)` | 4 |
| `IODPPortGetAddress` | `(ref, uint32_t*, uint32_t*, uint32_t*)` | |

`IODPPortGetAddress` takes three out-pointers. I called it with one — instant segfault, no message. The nesting bites too: `TimingElements` entries wrap `HorizontalAttributes`/`VerticalAttributes`, and grabbing the inner dict without looking reads the horizontal frequency (kHz) as a vertical rate. I spent a while wondering what a 343 Hz mode was.

## using it

Apple silicon, Xcode CLT (`clang`, `make`), and Python 3 with PyObjC Quartz for the switch/measure scripts (`pip install pyobjc-framework-Quartz`); the generator and parser are plain Python.

```sh
git clone https://github.com/owomocha/display360 && cd display360
make
./vedid edid > edid/mine.hex                    # your stock EDID as one hex line (read-only)
python3 parse_edid.py edid/mine.hex             # what it advertises, and where the timing lives
python3 build_edid.py edid/mine.hex --rate 360  # -> edid/mine-360.hex, plus the candidate table
./enable.sh edid/mine-360.hex 1920 360          # inject, rebuild, switch, count vsyncs for 5 s
python3 check.py --rate 360                      # is 360 in the DCP's usable table? in CoreGraphics?
```

Other geometry: `build_edid.py edid/mine.hex --rate 240 --width 2560 --height 1440`. Default candidates are the four blanking pairs that worked for me (`--blanking 200x80,216x90,160x80,160x64`, hblank×vblank, the first becomes preferred); the generator prints each one's vblank time and flags anything under 155 µs. The pixel-clock ceiling comes from your EDID's range-limits descriptor (`--force` to ignore). The bundled `edid/pixio-px259ps.hex` (no serial in it, I checked) and its `-360` sibling are also the defaults for `enable.sh` / `install.sh`, so the same monitor runs with no arguments. To undo: pick the old rate in System Settings, `setmode.py revert --rate 300`, or unplug.

The virtual EDID doesn't survive a replug, so to keep it on:

```sh
./install.sh edid/mine-360.hex 1920 360    # writes ~/Library/LaunchAgents/com.local.display360.plist, starts it
./uninstall.sh                             # stops and removes it, no sudo
```

`vedid daemon` sits on an IOKit matching notification for `DCPAVServiceProxy`, so it fires when a display connects: inject, rebuild, switch. It re-checks every 30 s and re-injects only if the mode vanished (sleep/wake eats it), won't override a rate you chose yourself while the mode is available, and matches the monitor by bytes 8–11 of the EDID so a different display does nothing. Log is `display360.log` next to the binary. When candidates don't appear, `python3 timings.py 100` prints the DCP's candidate table beside its usable one, `[usable]`/`[dropped]` per row — the fastest feedback loop I found; if everything drops, use fatter blanking, and if nothing even appears as a candidate the injection didn't take.

## caveats

`IOAVService*` / `IODP*` are all undocumented and a macOS update can break them without a word (`cgs_modes.py` likewise leans on the private `CGSGetDisplayModeDescriptionOfLength`). Candidate A drives the panel at 885.31 MHz, 7.5 % over its stock 360 Hz timing and 417.6 kHz horizontal — inside the EDID's declared 900 MHz max and fine here, but if yours flickers use the conservative single candidate (`--blanking 160x64`, D at 856.63 MHz). The virtual EDID is volatile: reboot, replug, and sleep all clear it, and the login window (before your session) stays at stock. I built this with SIP off for unrelated reasons and haven't tested SIP on — I'd expect the IOKit user clients to stay reachable, but that's a guess. If the screen goes black, `./vedid hpd` forces a hot-plug back to the wired EDID; nothing here writes outside the LaunchAgent plist in your home directory.

## files

`vedid.c` is the tool itself — EDID dump and injection, the DP device/port calls, hot-plug, and the daemon (subcommands `info edid set clear devupd ports pset hpd daemon`, one source line each). On the Python side, `build_edid.py` rewrites the DisplayID Type I block and recomputes both checksums, `parse_edid.py` decodes every block (base, CTA-861, DisplayID), `setmode.py` lists or selects a mode and counts real vsyncs (`revert` goes back), `check.py` is one-shot status, `timings.py` is the candidate-vs-usable diff, and `cgs_modes.py` lists hidden modes through the private CGS API. `enable.sh` chains inject→rebuild→switch→measure; `install.sh` / `uninstall.sh` toggle the LaunchAgent. `tests/` holds the generator's byte-for-byte reproduction of the shipped EDID plus the edge cases (`make test`); CI runs them on a macOS runner but can't exercise the injection — that needs a monitor on a real Mac.

MIT.
