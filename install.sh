#!/bin/sh
# Install the resident agent as a per-user LaunchAgent so the mode is re-applied on login, connect and wake.
#   ./install.sh [edid.hex] [width] [rate]     defaults: edid/pixio-px259ps-360.hex 1920 360
#   ./install.sh --print                       only print the plist that would be written (no changes)
set -e
cd "$(dirname "$0")"
DIR=$(pwd -P)
LABEL=com.local.display360
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
EDID=edid/pixio-px259ps-360.hex
WIDTH=1920
RATE=360
PRINT=0
n=0
for a in "$@"; do
  case "$a" in
    --print) PRINT=1 ;;
    *) n=$((n + 1)); case $n in 1) EDID=$a ;; 2) WIDTH=$a ;; 3) RATE=$a ;; esac ;;
  esac
done
case "$EDID" in /*) EDID_ABS=$EDID ;; *) EDID_ABS=$DIR/$EDID ;; esac

plist() {
cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DIR/vedid</string>
        <string>daemon</string>
        <string>$EDID_ABS</string>
        <string>$WIDTH</string>
        <string>$RATE</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>$DIR/display360.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/display360.log</string>
</dict>
</plist>
EOF
}

if [ "$PRINT" = 1 ]; then plist; exit 0; fi
[ -f "$EDID_ABS" ] || { echo "EDID file not found: $EDID (build one with build_edid.py)" >&2; exit 1; }
[ -x ./vedid ] || make
mkdir -p "$HOME/Library/LaunchAgents"
plist > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $PLIST  (vedid daemon $EDID $WIDTH $RATE)"
launchctl print "gui/$(id -u)/$LABEL" | grep -E '^[[:space:]]*(state|pid) =' | head -2 || true
