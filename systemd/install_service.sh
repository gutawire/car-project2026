#!/bin/bash
# One-time setup: install and enable the Driver Watch app as a systemd
# service, so it starts automatically on boot with no terminal/SSH needed.
# Run with sudo from anywhere.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo." >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_PATH="/etc/systemd/system/driverwatch.service"

sed "s#__PROJECT_DIR__#${PROJECT_DIR}#g" \
  "${PROJECT_DIR}/systemd/driverwatch.service.template" > "$UNIT_PATH"

systemctl daemon-reload
systemctl enable --now driverwatch.service

echo
echo "Installed and started driverwatch.service (project dir: ${PROJECT_DIR})."
echo "It will now start automatically on every boot - no terminal needed."
echo "Check status any time with: sudo systemctl status driverwatch"
echo "Watch logs with:            sudo journalctl -u driverwatch -f"
