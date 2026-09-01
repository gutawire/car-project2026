# Driver Watch

A drowsiness-detection RC car built on a Raspberry Pi. A phone's camera
streams video over WiFi to the Pi, which runs eye-open/closed detection
locally (OpenCV Haar cascades - no cloud, no internet needed) and stops the
car's motors + sounds a buzzer if the driver's eyes stay closed or their
face isn't visible.

Runs entirely offline: the Pi hosts its own WiFi hotspot, the phone connects
straight to it, and all detection happens on-device. No internet connection
is required at runtime - only for the one-time dependency install below.

## Hardware

- Raspberry Pi (tested on a Pi 4)
- L298N motor driver -> 2 DC motors (differential drive)
  - IN1/IN2/IN3/IN4 -> GPIO17/27/22/23 (BCM), ENA/ENB jumpers left in place
    (fixed speed - this project only controls direction/stop)
- Active buzzer -> GPIO24
- 16x2 I2C LCD (PCF8574 backpack, address 0x27 or 0x3f) -> SDA/SCL (GPIO2/3)
- Any phone with a camera and a modern browser

Every hardware module (`hardware/motors.py`, `hardware/buzzer.py`,
`hardware/lcd.py`) fails soft: if a piece of hardware isn't wired up yet,
it logs a one-time warning and no-ops instead of crashing the app, so you
can develop/test pieces incrementally.

## One-time setup

```bash
sudo apt update
sudo apt install -y python3-venv network-manager
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt
./generate_certs.sh          # self-signed TLS cert, not committed to git
sudo ./setup_hotspot.sh      # creates the car's own WiFi hotspot
```

`setup_hotspot.sh` accepts an optional SSID and password:
`sudo ./setup_hotspot.sh MyCarName mypassword123` (password must be 8+
characters). The hotspot is set as a *fallback* network - if you later join
the Pi to a "real" WiFi network via the in-app WiFi setup page (see below),
that network is preferred and the hotspot only comes back up when it's out
of range.

Optional but recommended for headless use - auto-start on boot so nobody
ever needs a terminal:

```bash
sudo ./systemd/install_service.sh
```

## Running it manually (skip if you installed the systemd service)

```bash
sudo ./venv/bin/python app.py
```

(root is required to bind port 443 and to access GPIO/I2C directly). Then,
on the phone: connect to the car's WiFi hotspot and open
`https://10.42.0.1` (nmcli's default hotspot gateway IP - no port needed,
the server listens on 443 so a bare IP defaults to the right scheme). The
LCD also shows the current IP if you have one wired up.

Your phone will show a "not secure" warning the first time - that's the
self-signed cert, tap through it.

## Using it

- Open the page, grant camera access. The car stays stopped until your
  eyes are confirmed open for half a second, then starts driving.
- If your eyes stay mostly closed for 1.5s, or your face isn't detected for
  2s, the car stops and the buzzer sounds.
- If the camera feed stalls entirely (phone locks, WiFi drops) for 1.5s
  while driving, the car stops automatically as a fail-safe - it does not
  keep driving on stale state.
- Reload the page or reconnect any time - it starts stopped, not driving,
  until it re-confirms you're alert.
- **Hardware Test panel** on the main page: hold a direction button to
  jog the motors (forward/back/left/right), hold the buzzer button to test
  it. Release to stop. Useful for checking wiring without triggering the
  full drowsiness flow. Only one phone can be connected at a time.

## Joining the car to your own WiFi (no screen needed)

If you want the Pi on a "real" WiFi network (e.g. a venue's WiFi) instead
of just its own isolated hotspot, and you only have a phone (no keyboard,
no screen, no SSH):

1. Connect your phone to the car's own hotspot (SSID/password from
   `setup_hotspot.sh`).
2. Open `https://10.42.0.1/wifi`.
3. Tap "Scan for networks", pick one, enter its password, and connect.

**Heads up:** a Pi normally has one WiFi radio, so switching it from
hotspot mode to join a network drops your phone's connection to the page
immediately - that's expected. Reconnect your phone to the same network
(or back to the car's hotspot, if the join failed) to check the result.
Once joined, that network is preferred on future boots; the car's own
hotspot only comes back up automatically if that network isn't in range.

## Project layout

```
app.py                  Flask + Socket.IO server: frame intake, drowsiness
                         state machine, hardware test / WiFi routes
network.py               nmcli wrappers: IP lookup, WiFi scan/join
drowsiness/detector.py   Haar-cascade eye-open/closed/no-face classifier
hardware/                motors.py, buzzer.py, lcd.py - fail-soft GPIO/I2C
templates/, static/      phone-facing UI (index.html + WiFi setup page)
assets/haarcascades/     bundled OpenCV cascade files
setup_hotspot.sh          one-time: create the car's WiFi hotspot
generate_certs.sh         one-time: generate the self-signed TLS cert
systemd/                  optional: auto-start the app on boot
```

## Why Haar cascades, not MediaPipe

MediaPipe's Face Landmarker (a more accurate, EAR-based approach) was
evaluated and ruled out on this hardware: its compiled binary requires AES
CPU extensions that a Raspberry Pi 4's Cortex-A72 doesn't expose, which
crashes the whole process with an illegal instruction (SIGILL) - not a
catchable Python exception. OpenCV's bundled Haar cascades are slower to
tune but reliable to run, with no native-crash risk.

## Diagnostics

- `python hardware/i2c_test.py` - raw I2C bus scan, to check LCD wiring
  independent of the RPLCD library.
- `python -m drowsiness.detector <image_path>` - run the eye-state
  classifier on a single image file.
- `python -m hardware.motors` / `python -m hardware.buzzer` - jog the
  motors / beep the buzzer for a couple seconds from the command line.
