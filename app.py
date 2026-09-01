import base64
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

import network
from drowsiness.detector import eye_state
from hardware import buzzer, lcd, motors

app = Flask(__name__)
app.config["SECRET_KEY"] = "drowsiness-demo"
socketio = SocketIO(app, cors_allowed_origins="*")

CLOSED_EYES_STOP_SECONDS = 1.5
NO_FACE_STOP_SECONDS = 2.0
RESUME_DEBOUNCE_SECONDS = 0.5
# Fraction of frames within the relevant window that must agree before we
# act on them - a single spurious detection (a noisy Haar-cascade hit) can't
# by itself reset or trigger a stop, only a sustained trend can.
STOP_RATIO_THRESHOLD = 0.8
# How long a frame gap is tolerated before we assume the camera feed died
# and stop as a fail-safe, instead of continuing to drive on stale state.
FRAME_TIMEOUT_SECONDS = 1.5
HISTORY_WINDOW_SECONDS = max(CLOSED_EYES_STOP_SECONDS, NO_FACE_STOP_SECONDS)

state = {
    "driving": False,  # stay stopped until a client is verified alert
    "client_sid": None,
    "history": deque(),  # (timestamp, EyeState) pairs, oldest first
    "open_since": None,
    "last_frame_at": None,
    "manual_override": False,  # a hardware test button is currently held
}

MANUAL_ACTIONS = {
    "forward": motors.forward,
    "backward": motors.backward,
    "left": motors.left,
    "right": motors.right,
}


def show_connect_info() -> None:
    ip = network.get_display_ip()
    if ip:
        lcd.set_status(ip, "Connect here")
    else:
        lcd.set_status("No network", "connection")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/wifi")
def wifi_page():
    return render_template("wifi.html")


@app.route("/wifi/networks")
def wifi_networks():
    return jsonify([n.__dict__ for n in network.scan_networks()])


@app.route("/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.get_json(silent=True) or {}
    ok, message = network.connect_network(data.get("ssid", "").strip(), data.get("password", ""))
    if ok:
        show_connect_info()
    return jsonify({"ok": ok, "message": message})


def _start_driving() -> None:
    state["driving"] = True
    motors.go()
    buzzer.alert_off()
    lcd.set_status("AWAKE", "Driving")


def _stop_driving(line1: str, line2: str) -> None:
    if not state["driving"]:
        return
    state["driving"] = False
    state["open_since"] = None
    motors.stop()
    buzzer.alert_on()
    lcd.set_status(line1, line2)


def _reset_session_state() -> None:
    state.update(driving=False, history=deque(), open_since=None, last_frame_at=None,
                 manual_override=False)


@socketio.on("connect")
def on_connect():
    if state["client_sid"] is not None:
        print("[app] rejecting connection - a client is already active")
        return False  # refuse the connection
    state["client_sid"] = request.sid
    _reset_session_state()
    motors.stop()
    buzzer.alert_off()
    lcd.set_status("Waiting for", "camera feed")
    print("[app] client connected")


@socketio.on("disconnect")
def on_disconnect():
    if request.sid != state["client_sid"]:
        return
    state["client_sid"] = None
    state["manual_override"] = False
    motors.stop()
    buzzer.alert_off()
    show_connect_info()
    print("[app] client disconnected")


@socketio.on("manual_control")
def on_manual_control(data):
    """Hardware test panel: forward/backward/left/right while held, stop on
    release. Only usable by the one connected client, and takes priority
    over the autonomous drowsiness logic while a direction is held so the
    two don't fight over the motors."""
    action = (data or {}).get("action")
    handler = MANUAL_ACTIONS.get(action)
    if handler is None:
        state["manual_override"] = False
        motors.stop()
        return
    state["manual_override"] = True
    handler()


@socketio.on("manual_buzzer")
def on_manual_buzzer(data):
    """Hardware test panel: buzzer on while held, off on release."""
    if (data or {}).get("on"):
        buzzer.alert_on()
    else:
        buzzer.alert_off()


def _watchdog() -> None:
    """Fail-safe: if frames stop arriving (camera died, phone slept, network
    stalled) while still "driving", stop rather than keep acting on stale
    state forever."""
    while True:
        socketio.sleep(0.5)
        last = state["last_frame_at"]
        if last is None or not state["driving"]:
            continue
        if time.time() - last >= FRAME_TIMEOUT_SECONDS:
            _stop_driving("NO SIGNAL", "STOPPED")
            socketio.emit("status", {"eye_state": "no_face", "driving": False})


def _recent_ratio(now: float, window_seconds: float, target: str) -> float:
    cutoff = now - window_seconds
    relevant = [r for t, r in state["history"] if t >= cutoff]
    return (sum(1 for r in relevant if r == target) / len(relevant)) if relevant else 0.0


_frame_count = 0


@socketio.on("frame")
def on_frame(data):
    global _frame_count
    _frame_count += 1
    if _frame_count == 1 or _frame_count % 40 == 0:
        print(f"[app] frame #{_frame_count} received ({len(data)} bytes b64)")
    now = time.time()
    state["last_frame_at"] = now
    b64 = data.split(",", 1)[1] if "," in data else data
    jpg = base64.b64decode(b64)
    arr = np.frombuffer(jpg, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return

    result = eye_state(frame)
    if _frame_count == 1 or _frame_count % 40 == 0:
        print(f"[app] eye_state -> {result}")

    state["history"].append((now, result))
    cutoff = now - HISTORY_WINDOW_SECONDS
    while state["history"] and state["history"][0][0] < cutoff:
        state["history"].popleft()

    if result == "open":
        state["open_since"] = state["open_since"] or now
    else:
        state["open_since"] = None

    if not state["manual_override"]:
        if state["driving"]:
            if _recent_ratio(now, CLOSED_EYES_STOP_SECONDS, "closed") >= STOP_RATIO_THRESHOLD:
                _stop_driving("DROWSY!", "STOPPED")
            elif _recent_ratio(now, NO_FACE_STOP_SECONDS, "no_face") >= STOP_RATIO_THRESHOLD:
                _stop_driving("NO FACE", "STOPPED")
        elif state["open_since"] and now - state["open_since"] >= RESUME_DEBOUNCE_SECONDS:
            _start_driving()

    socketio.emit("status", {"eye_state": result, "driving": state["driving"]})


if __name__ == "__main__":
    show_connect_info()
    socketio.start_background_task(_watchdog)
    # Port 443 (the standard HTTPS port) so a phone browser defaults to the
    # right scheme/port automatically when just the bare IP is typed in -
    # avoids the recurring http-vs-https mixup of a non-standard port.
    certs_dir = Path(__file__).parent / "certs"
    socketio.run(app, host="0.0.0.0", port=443, debug=False,
                 certfile=str(certs_dir / "cert.pem"),
                 keyfile=str(certs_dir / "key.pem"))
