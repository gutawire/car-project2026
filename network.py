"""WiFi status/scan/join helpers, all backed by nmcli (NetworkManager).

Lets someone with only a phone - no keyboard, no screen, on a network the
Pi has never seen - get the Pi onto their WiFi: connect the phone to the
Pi's own hotspot (see setup_hotspot.sh), open the /wifi page served over
that hotspot, and join a network from there. Everything here shells out to
nmcli with an argument list (never shell=True) so a password containing
shell metacharacters can't do anything unexpected.
"""
import re
import subprocess
from dataclasses import dataclass

NMCLI_TIMEOUT_SECONDS = 10


def get_display_ip() -> str | None:
    """Best-effort IP to show on the LCD so someone can connect without a
    terminal. Prefers wlan0 (the hotspot/WiFi) over eth0 since that's what
    the phone actually needs to join."""
    for iface in ("wlan0", "eth0"):
        try:
            out = subprocess.run(
                ["nmcli", "-g", "IP4.ADDRESS", "device", "show", iface],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip()
            if out:
                return out.split("/")[0]
        except Exception:
            continue
    return None


@dataclass
class WifiNetwork:
    ssid: str
    signal: int
    secure: bool
    in_use: bool


def _unescape_nmcli(field: str) -> str:
    # nmcli terse output (-t) escapes ':' and '\' inside field values.
    return field.replace("\\:", ":").replace("\\\\", "\\")


def _split_nmcli_line(line: str) -> list[str]:
    return re.split(r"(?<!\\):", line)


def scan_networks() -> list[WifiNetwork]:
    """List nearby WiFi networks, strongest first, deduplicated by SSID."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, timeout=NMCLI_TIMEOUT_SECONDS,
        )
    except Exception:
        return []

    best: dict[str, WifiNetwork] = {}
    for line in result.stdout.splitlines():
        parts = _split_nmcli_line(line)
        if len(parts) < 4:
            continue
        in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
        ssid = _unescape_nmcli(ssid).strip()
        if not ssid:
            continue  # hidden network, nothing to show/select
        try:
            signal_val = int(signal)
        except ValueError:
            signal_val = 0
        existing = best.get(ssid)
        if existing is None or signal_val > existing.signal:
            best[ssid] = WifiNetwork(
                ssid=ssid,
                signal=signal_val,
                secure=bool(security.strip()),
                in_use=(in_use.strip() == "*"),
            )
    return sorted(best.values(), key=lambda n: n.signal, reverse=True)


def connect_network(ssid: str, password: str) -> tuple[bool, str]:
    """Join a WiFi network by SSID/password. Returns (success, message)."""
    if not ssid:
        return False, "SSID is required."

    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out trying to join that network."
    except Exception as exc:
        return False, f"Could not run nmcli: {exc}"

    if result.returncode == 0:
        return True, f"Connected to {ssid}."
    return False, (result.stderr or result.stdout or "Failed to connect.").strip()
