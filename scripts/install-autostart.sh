#!/usr/bin/env bash
# macOS: run the shopkeeper web server automatically at login (launchd LaunchAgent).
# It also restarts the server if it ever crashes. Re-run this to update.
#
#   ./scripts/install-autostart.sh
#
# Stop / uninstall:
#   launchctl bootout gui/$(id -u)/com.shopkeeper.web
#   rm ~/Library/LaunchAgents/com.shopkeeper.web.plist
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.shopkeeper.web"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/shopkeeper-web.log"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$DIR/.venv/bin/shopkeeper-web</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

# Free the port: stop any manually-started server first.
pkill -f shopkeeper-web 2>/dev/null || true
sleep 1

# (Re)load the agent.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"

echo "installed $LABEL — starts at login, restarts on crash."
echo "logs: $LOG"
echo "uninstall: launchctl bootout gui/\$(id -u)/$LABEL && rm '$PLIST'"
