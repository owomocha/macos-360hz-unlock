#!/bin/sh
# Apply the target mode now: inject the EDID, make the DCP rebuild its timings, switch, measure.
#   ./enable.sh [edid.hex] [width] [rate]      defaults: edid/pixio-px259ps-360.hex 1920 360
# Needed again after every reboot / replug unless the LaunchAgent is installed (install.sh).
set -e
cd "$(dirname "$0")"
EDID=${1:-edid/pixio-px259ps-360.hex}
WIDTH=${2:-1920}
RATE=${3:-360}
[ -f ./local.env ] && . ./local.env          # optional, gitignored: PYTHON=/path/to/python-with-pyobjc
PY=${PYTHON:-python3}
"$PY" -c 'import Quartz' 2>/dev/null || {
  echo "need a Python with PyObjC Quartz: pip install pyobjc-framework-Quartz (or set PYTHON=...)" >&2; exit 1; }
[ -f "$EDID" ] || { echo "EDID file not found: $EDID (build one with build_edid.py)" >&2; exit 1; }
[ -x ./vedid ] || make
out=$(./vedid set "$EDID") || { printf '%s\n' "$out" >&2; exit 1; }   # stop here if the DCP refused it
printf '%s\n' "$out" | tail -1
./vedid devupd 1 | tail -1
sleep 2
"$PY" setmode.py --width "$WIDTH" --rate "$RATE" 0
