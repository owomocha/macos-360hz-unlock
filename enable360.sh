#!/bin/sh
# Apply 360 Hz now. Needed again after every reboot / replug unless the LaunchAgent is installed.
#   1) inject the virtual EDID (with the 360 Hz timings) into the DCP
#   2) tell the DP device it was updated so the DCP rebuilds its timing table
#   3) switch to the 360 Hz mode and count real vsyncs for 5 s
set -e
cd "$(dirname "$0")"
[ -f ./local.env ] && . ./local.env          # optional, gitignored: PYTHON=/path/to/python-with-pyobjc
PY=${PYTHON:-python3}
"$PY" -c 'import Quartz' 2>/dev/null || {
  echo "need a Python with PyObjC Quartz: pip install pyobjc-framework-Quartz (or set PYTHON=...)" >&2; exit 1; }
./vedid set edid_v2.hex | tail -1
./vedid devupd 1        | tail -1
sleep 2
"$PY" set360.py 0
