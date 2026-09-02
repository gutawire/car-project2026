import base64
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

import network
from drowsiness.detector import detect
from hardware import buzzer, lcd, motors

app = Flask(__name__)
app.config["SECRET_KEY"] = "drowsiness-demo"
socketio = SocketIO(app, cors_allowed_origins="*")

CLOSED_EYES_WARN_SECONDS = 1.5
NO_FACE_WARN_SECONDS = 2.0
RESUME_DEBOUNCE_SECONDS = 0.5
# Fraction of frames within the relevant window that must agree before we
# act on them - a single spurious detection (a noisy Haar-cascade hit) can't
# by itself trigger a warning, only a sustained trend can.
STOP_RATIO_THRESHOLD = 0.8
# Once a drowsy/no-face condition is flagged, the buzzer sounds and the car
# keeps driving for this long before actually stopping - a warning beep the
# driver can react to, not an instant slam to a halt.
WARNING_DURATION_SECONDS = 2.5
# How long a frame gap is tolerated before we assume the camera feed died
# and stop as a fail-safe, instead of continuing to drive on stale state.
FRAME_TIMEOUT_SECONDS = 1.5
HISTORY_WINDOW_SECONDS = max(CLOSED_EYES_WARN_SECONDS, NO_FACE_WARN_SECONDS)

state = {
    "armed": False,  # only true once the phone explicitly taps "Start Driving"
    "driving": False,
    "client_sid": None,
    "history": deque(),  # (timestamp, EyeState) pairs, oldest first
    "open_since": None,
    "last_frame_at": None,
    "manual_override": False,  # a hardware test button is currently held
    "warning_since": None,  # set while beeping but still driving, pre-stop
    "warning_reason": None,  # (line1, line2) to show once the warning elapses
    "alarm": False,  # whether the buzzer is currently sounding
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
    state["warning_since"] = None
    state["warning_reason"] = None
    state["alarm"] = False
    motors.go()
    buzzer.alert_off()
    lcd.set_status("AWAKE", "Driving")


def _begin_warning(line1: str, line2: str) -> None:
    """Drowsy/no-face condition just got flagged: beep and show it, but
    keep driving - _stop_driving only runs if it's still unresolved after
    WARNING_DURATION_SECONDS."""
    state["warning_since"] = time.time()
    state["warning_reason"] = (line1, line2)
    state["alarm"] = True
    buzzer.alert_on()
    lcd.set_status(line1, "Wake up!")


def _cancel_warning() -> None:
    """Driver responded (eyes back open) before the warning elapsed."""
    state["warning_since"] = None
    state["warning_reason"] = None
    state["alarm"] = False
    buzzer.alert_off()
    lcd.set_status("AWAKE", "Driving")


def _stop_driving(line1: str, line2: str, alarm: bool = True) -> None:
    # Disarm on every stop (drowsy, no-signal, or manual): eyes reopening
    # alone must never resume driving on its own - the phone has to send a
    # fresh "start_session" to continue, same as the very first start.
    state["armed"] = False
    state["driving"] = False
    state["open_since"] = None
    state["warning_since"] = None
    state["warning_reason"] = None
    state["alarm"] = alarm
    motors.stop()
    if alarm:
        buzzer.alert_on()
    else:
        buzzer.alert_off()
    lcd.set_status(line1, line2)


def _reset_session_state(armed: bool = False) -> None:
    state.update(driving=False, history=deque(), open_since=None, last_frame_at=None,
                 manual_override=False, warning_since=None, warning_reason=None, armed=armed)


@socketio.on("connect")
def on_connect():
    if state["client_sid"] is not None:
        print("[app] rejecting connection - a client is already active")
        return False  # refuse the connection
    state["client_sid"] = request.sid
    _reset_session_state()
    motors.stop()
    buzzer.alert_off()
    lcd.set_status("Tap Start", "on phone")
    print("[app] client connected")


@socketio.on("disconnect")
def on_disconnect():
    if request.sid != state["client_sid"]:
        return
    state["client_sid"] = None
    state["manual_override"] = False
    state["armed"] = False
    motors.stop()
    buzzer.alert_off()
    show_connect_info()
    print("[app] client disconnected")


@socketio.on("start_session")
def on_start_session():
    """Phone tapped "Start Driving" - arms the drowsiness logic. The car
    stays stopped until eyes are then confirmed open for RESUME_DEBOUNCE_SECONDS,
    same as any other resume."""
    if request.sid != state["client_sid"]:
        return
    _reset_session_state(armed=True)
    motors.stop()
    buzzer.alert_off()
    lcd.set_status("Waiting for", "eyes open")
    print("[app] session started (armed)")


@socketio.on("stop_session")
def on_stop_session():
    """Phone tapped "Stop" - immediate, no warning beep, and disarms until
    the phone starts a new session."""
    if request.sid != state["client_sid"]:
        return
    state["armed"] = False
    _stop_driving("STOPPED", "by phone", alarm=False)
    print("[app] session stopped (disarmed)")


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
            socketio.emit("status", {
                "eye_state": "no_face", "driving": False, "armed": state["armed"],
                "warning": False, "warning_seconds_left": None, "alarm": state["alarm"],
                "face": None, "eyes": [], "frame_number": _frame_count, "server_time": time.time(),
            })


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

    detection = detect(frame)
    result = detection.state
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

    if not state["manual_override"] and state["armed"]:
        if state["driving"]:
            closed_bad = _recent_ratio(now, CLOSED_EYES_WARN_SECONDS, "closed") >= STOP_RATIO_THRESHOLD
            no_face_bad = _recent_ratio(now, NO_FACE_WARN_SECONDS, "no_face") >= STOP_RATIO_THRESHOLD
            if closed_bad or no_face_bad:
                reason = ("DROWSY!", "STOPPED") if closed_bad else ("NO FACE", "STOPPED")
                if state["warning_since"] is None:
                    _begin_warning(*reason)
                elif now - state["warning_since"] >= WARNING_DURATION_SECONDS:
                    _stop_driving(*state["warning_reason"])
            elif state["warning_since"] is not None:
                _cancel_warning()
        elif state["open_since"] and now - state["open_since"] >= RESUME_DEBOUNCE_SECONDS:
            _start_driving()

    warning_seconds_left = None
    if state["warning_since"] is not None:
        warning_seconds_left = max(0.0, WARNING_DURATION_SECONDS - (now - state["warning_since"]))

    socketio.emit("status", {
        "eye_state": result,
        "driving": state["driving"],
        "armed": state["armed"],
        "warning": state["warning_since"] is not None,
        "warning_seconds_left": warning_seconds_left,
        "alarm": state["alarm"],
        "face": detection.face,
        "eyes": detection.eyes,
        "frame_number": _frame_count,
        "server_time": time.time(),
    })


if __name__ == "__main__":
    # Branded boot splash so the LCD immediately proves the app is alive,
    # before switching to the actually-useful connect-info screen - without
    # this, a blank/generic LCD at boot is indistinguishable from a wiring
    # fault or the service having failed to start.
    lcd.set_status("DRIVER WATCH", "Starting...")
    time.sleep(2)
    show_connect_info()
    socketio.start_background_task(_watchdog)
    # Port 443 (the standard HTTPS port) so a phone browser defaults to the
    # right scheme/port automatically when just the bare IP is typed in -
    # avoids the recurring http-vs-https mixup of a non-standard port.
    certs_dir = Path(__file__).parent / "certs"
    socketio.run(app, host="0.0.0.0", port=443, debug=False,
                 certfile=str(certs_dir / "cert.pem"),
                 keyfile=str(certs_dir / "key.pem"))
