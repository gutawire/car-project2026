"""Active buzzer alert via gpiozero.

Wiring (BCM numbering) - a free pin, not used by motors (17/27/22/23) or
the I2C LCD (2/3):
    Signal -> GPIO24
    GND    -> any Pi GND pin
"""
from gpiozero import Buzzer

BUZZER_PIN = 24

_buzzer = None
_unavailable = False  # set once GPIO claiming fails, to stop retrying every frame


def _get_buzzer() -> Buzzer:
    global _buzzer
    if _buzzer is None:
        _buzzer = Buzzer(BUZZER_PIN)
    return _buzzer


def alert_on() -> None:
    """Start a pulsing alert tone. No-ops (with a one-time warning) if the
    GPIO pin can't be claimed, so the rest of the app keeps running."""
    global _unavailable
    if _unavailable:
        return
    try:
        _get_buzzer().beep(on_time=0.4, off_time=0.4, background=True)
    except Exception as exc:
        _unavailable = True
        print(f"[buzzer] not available ({exc}) - buzzer output disabled for this run.")


def alert_off() -> None:
    global _unavailable
    if _unavailable:
        return
    try:
        _get_buzzer().off()
    except Exception as exc:
        _unavailable = True
        print(f"[buzzer] not available ({exc}) - buzzer output disabled for this run.")


if __name__ == "__main__":
    import time

    print("Beeping for 2s...")
    alert_on()
    time.sleep(2)
    print("Stopping.")
    alert_off()
