# Changelog

## v0.3.0 (2026-09-09)

Re-measured on the real monitor with the generic daemon doing the injection on a fresh connect: 359.9923 Hz, 1802 frames in 5.003 s (until now v0.2 had only met the Dell, which it correctly ignored). The blanking rule is a chart in the README now.

- `build_edid.py`: a DisplayID section that starts with a v1.x Product ID block (tag 0x00) no longer reads as "no Type I block"; the parser stops at zero padding, not at the first zero tag. The rewritten Type I block stays where the monitor put it, other blocks keep their order, and a second Type I block is preserved instead of dropped. Too many candidates now gets the size error rather than a `bytes` ValueError
- `parse_edid.py`: no longer walks through the DisplayID section's zero padding and checksums (it printed dozens of `tag=0x00` lines); prints a checksum verdict per block, decodes bit depth / interface, the 0xFE text descriptor and the DisplayID 1.x / 2.x block names, and a CTA block with no DTDs (offset 0) is no longer read as one. Usage and a clean error instead of a traceback on a missing or odd file
- `check.py`: the DCP table check reads only `VerticalAttributes` (the horizontal dict has a `SyncRate` too, in kHz) and compares within 1.5 Hz instead of exact 1/65536 units, so `--rate 359.99` matches the 360 Hz entry and a 295 kHz line rate does not match `--rate 295`. The verdict and `--set` now agree on which candidate they mean
- `timings.py`: elements without `Score` / `UnsafeColorElementIDs` / `PreciseSyncRate` no longer crash it; says so when there are no `TimingElements` at all; bad `min_hz` prints usage
- `cgs_modes.py`: the 1920x1080-or-200 Hz filter left over from the Pixio days is gone; takes `[min_hz]` like `timings.py` and sorts fastest first
- `setmode.py`: a bad candidate index is an error message, not a traceback; survives `CGGetOnlineDisplayList` returning nothing
- `enable.sh`: stops with `vedid set`'s own message when the injection fails instead of going on to a misleading "no such mode"
- issue template for "my monitor's mode doesn't show up" asking for the EDID and the DCP tables; tests for `parse_edid.py`, `check.py`, `timings.py` and the DisplayID parsing

## v0.2.0 (2026-09-07)

The tool stops being Pixio-only.

- `vedid daemon <edid> [width] [rate]`: the target mode is an argument and the monitor's manufacturer/product ID is read from the EDID it is given, instead of a hard-coded PX259PS check
- `build_edid.py` replaces `build_edid2.py`: any resolution and rate, blanking candidates and sync widths as arguments, the pixel-clock ceiling read from the EDID's own range limits, clear errors when the EDID has no DisplayID Type I block or the section is full
- `vedid edid` prints the wired EDID as one hex line, so `./vedid edid > edid/mine.hex` is the whole dump step
- `setmode.py` (was `set360.py`) and `check.py` take `--width` / `--rate`; `enable.sh` (was `enable360.sh`) and `install.sh` take `edid width rate`
- everything prints English now, and `vedid.c` is commented in English
- `Makefile`, `tests/` (the generator must reproduce the shipped EDID byte for byte) and a macOS CI workflow
- `edid.hex` / `edid_v2.hex` moved to `edid/pixio-px259ps.hex` / `edid/pixio-px259ps-360.hex`

## v0.1.0 (2026-09-07)

First public version. The actual work happened on 2026-08-31; this is that state, cleaned up.

- `vedid`: virtual EDID injection (`IOAVServiceSetVirtualEDIDMode`) + timing table rebuild (`IODPDeviceSetUpdated`), daemon mode with connect notifications and a 30 s check
- `build_edid2.py`: DisplayID Type I generator with the four 360 Hz candidates, both checksums recomputed
- `set360.py`, `check.py`, `timings.py`, `parse_edid.py`, `cgs_modes.py`: switching, measuring, poking at the DCP timing tables
- `install.sh` / `uninstall.sh`: LaunchAgent on/off
