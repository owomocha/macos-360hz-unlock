# Changelog

## v0.1.0 (2026-09-07)

First public version. The actual work happened on 2026-08-31; this is that state, cleaned up.

- `vedid`: virtual EDID injection (`IOAVServiceSetVirtualEDIDMode`) + timing table rebuild (`IODPDeviceSetUpdated`), daemon mode with connect notifications and a 30 s check
- `build_edid2.py`: DisplayID Type I generator with the four 360 Hz candidates, both checksums recomputed
- `set360.py`, `check.py`, `timings.py`, `parse_edid.py`, `cgs_modes.py`: switching, measuring, poking at the DCP timing tables
- `install.sh` / `uninstall.sh`: LaunchAgent on/off
