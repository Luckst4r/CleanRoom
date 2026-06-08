#!/usr/bin/env bash
# Install a launchd agent so the CleanRoom detector starts at login and stays
# running (restarts if it crashes). macOS only. Run on the Mac mini:
#   bash scripts/install-service.sh
#
# IMPORTANT: stop any manually-run `python app.py` first (Ctrl-C), or the service
# and the manual copy will fight over port 8080.
set -euo pipefail

DETECTOR_DIR="$HOME/CleanRoom/detector"
PYTHON="$DETECTOR_DIR/.venv/bin/python"
LABEL="com.cleanroom.detector"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/CleanRoom/detector.log"

if [ ! -x "$PYTHON" ]; then
  echo "Error: $PYTHON not found — set up the detector venv first (docs/DEPLOY.md)." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$DETECTOR_DIR/app.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DETECTOR_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

# (Re)load, preferring the modern launchctl API and falling back to the legacy one.
DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"

echo "Installed and started: $LABEL"
echo "  plist: $PLIST"
echo "  logs:  $LOG"
echo
echo "Check it:  curl -s http://localhost:8080/status | head -c 200; echo"
echo "Stop it:   launchctl bootout $DOMAIN/$LABEL   (or: launchctl unload $PLIST)"
