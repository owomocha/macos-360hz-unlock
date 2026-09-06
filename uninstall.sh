#!/bin/sh
# Stop and remove the LaunchAgent. No sudo. The virtual EDID is volatile, so the
# display returns to its stock timings on the next replug or reboot.
set -e
LABEL=com.local.display360
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "stopped $LABEL" || echo "$LABEL was not running"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" && echo "removed $HOME/Library/LaunchAgents/$LABEL.plist"
echo "(replug the cable or reboot to get the stock refresh rates back)"
