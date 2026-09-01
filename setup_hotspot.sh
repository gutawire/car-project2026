#!/bin/bash
# One-time setup: turn the Pi's wlan0 into a WiFi hotspot so a phone can
# connect directly (no router/internet required). Run with sudo.
#
# Usage: sudo ./setup_hotspot.sh [ssid] [password]
set -euo pipefail

SSID="${1:-DriverWatchCar}"
PASSWORD="${2:-drivewatch123}"
CON_NAME="driverwatch-hotspot"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo." >&2
  exit 1
fi

if [ "${#PASSWORD}" -lt 8 ]; then
  echo "WPA2 password must be at least 8 characters." >&2
  exit 1
fi

nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true

nmcli device wifi hotspot \
  ifname wlan0 \
  con-name "$CON_NAME" \
  ssid "$SSID" \
  password "$PASSWORD"

nmcli connection modify "$CON_NAME" connection.autoconnect yes
# Lower priority than any regular WiFi profile (default priority 0), so
# NetworkManager only falls back to this hotspot when no known network
# (including one added later via the app's /wifi page) is in range.
nmcli connection modify "$CON_NAME" connection.autoconnect-priority -10

echo
echo "Hotspot '$SSID' is up as a fallback network (lower priority than any"
echo "WiFi you join later via the app's /wifi page). Connect your phone to"
echo "it now, then open https://10.42.0.1 (nmcli's fixed hotspot gateway"
echo "IP - no port needed, server runs on 443). If that doesn't work, find"
echo "the Pi's actual IP with:"
echo "  nmcli -g IP4.ADDRESS device show wlan0"
