# Changelog

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
