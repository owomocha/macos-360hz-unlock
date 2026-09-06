#!/bin/sh
# Remove the display360 LaunchAgent and return to the stock refresh rates.
#   1) stop and delete the agent            (no sudo)
#   2) optionally delete the legacy EDID override (only ever changed the display name; needs sudo)
set -e
LABEL=com.local.display360
echo "--- 1) LaunchAgent ---"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "stopped $LABEL" || echo "$LABEL was not running"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" && echo "removed plist"
echo "(the virtual EDID is volatile: the display returns to stock timings on the next replug or reboot)"

echo "--- 2) legacy EDID override (optional) ---"
OVR="/Library/Displays/Contents/Resources/Overrides/DisplayVendorID-430f/DisplayProductID-2500"
if [ -f "$OVR" ]; then
  sudo rm -f "$OVR" && echo "removed $OVR"
  sudo rmdir "$(dirname "$OVR")" 2>/dev/null || true
else
  echo "no override present"
fi
