---
name: My monitor's mode doesn't show up
about: The rate you built an EDID for never appears in System Settings
title: "<monitor>: <width>x<height> @ <rate> not accepted"
labels: ""
---

I've only ever run this against one monitor, so if yours behaves differently I want the raw data, not a description of it. Paste these and I can usually tell whether the DCP rejected the timing or the injection never took.

**Monitor** (model, and how it's connected: USB-C / DP / HDMI, any dock):

**Mac and macOS** (`sysctl hw.model` / `sw_vers`):

**What you ran and what it printed** (the `build_edid.py` command with its candidate table, then `enable.sh` or `check.py`):

```
```

**Your stock EDID** (`./vedid edid`, one hex line — it has no serial number unless your monitor puts one in the descriptor, check `parse_edid.py` first if that worries you):

```
```

**The DCP's candidate vs. usable tables** (`python3 timings.py 100`). If your rate is in the candidates but marked `[dropped]`, the blanking is too short; if it isn't even a candidate, the injection didn't take:

```
```
