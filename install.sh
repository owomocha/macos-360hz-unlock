#!/bin/sh
# Install display360 as a per-user LaunchAgent: 360 Hz is re-applied on login, connect and wake.
#   ./install.sh [edid.hex]     build vedid if missing, write the plist, (re)start the agent
#   ./install.sh --print        only print the plist that would be written (no changes)
set -e
cd "$(dirname "$0")"
DIR=$(pwd -P)
LABEL=com.local.display360
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
EDID=edid_v2.hex
PRINT=0
for a in "$@"; do
  case "$a" in
    --print) PRINT=1 ;;
    *) EDID=$a ;;
  esac
done

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
        <string>$DIR/$EDID</string>
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
[ -f "$EDID" ] || { echo "EDID file not found: $EDID (run: python3 build_edid2.py)" >&2; exit 1; }
if [ ! -x ./vedid ]; then
  echo "building vedid..."
  clang -O2 -o vedid vedid.c -framework IOKit -framework CoreFoundation -framework CoreGraphics
fi
mkdir -p "$HOME/Library/LaunchAgents"
plist > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $PLIST"
launchctl print "gui/$(id -u)/$LABEL" | grep -E '^[[:space:]]*(state|pid) =' | head -2 || true
