#!/usr/bin/env bash
# Generate a self-signed TLS certificate so the phone camera works
# (browsers only allow camera access over HTTPS). The phone shows a one-time
# "not private" warning you accept once. Re-run to refresh (e.g. new IP).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs
IP="$(python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',80));print(s.getsockname()[0]);s.close()" 2>/dev/null || echo 127.0.0.1)"
HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=shopkeeper" \
  -addext "subjectAltName=DNS:${HOST}.local,DNS:localhost,IP:${IP},IP:127.0.0.1" 2>/dev/null
chmod 600 certs/key.pem
echo "cert created — valid for: ${HOST}.local, ${IP}, localhost"
echo "phone URL: https://${HOST}.local:8765"
