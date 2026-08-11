#!/usr/bin/env bash
# Linux: run the shopkeeper web server 24/7 as a systemd *user* service.
# Starts at boot (via lingering, no login needed) and restarts on crash.
# Re-run this any time to update. macOS uses install-autostart.sh (launchd) instead.
#
#   ./scripts/install-autostart-linux.sh
#
# Stop / uninstall:
#   systemctl --user disable --now shopkeeper-web
#   rm ~/.config/systemd/user/shopkeeper-web.service
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/shopkeeper-web.service"

if [ ! -x "$DIR/.venv/bin/shopkeeper-web" ]; then
  echo "error: $DIR/.venv/bin/shopkeeper-web not found — create the venv first:" >&2
  echo "  python3.13 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=Shopkeeper web server
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/shopkeeper-web
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

# Run at boot even when nobody is logged in.
loginctl enable-linger "$USER" 2>/dev/null || \
  echo "note: could not enable lingering (may need: sudo loginctl enable-linger $USER)"

systemctl --user daemon-reload
systemctl --user enable --now shopkeeper-web

echo "shopkeeper-web is now running as a systemd user service."
echo "  status:  systemctl --user status shopkeeper-web"
echo "  logs:    journalctl --user -u shopkeeper-web -f"
echo "  restart: systemctl --user restart shopkeeper-web"
