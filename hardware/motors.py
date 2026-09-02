"""L298N motor control via gpiozero.

Wiring (BCM numbering) - leave the L298N's ENA/ENB jumpers in place (fixed
speed); this module only controls direction/stop, not speed:
    IN1 (left fwd)   -> GPIO17
    IN2 (left back)  -> GPIO27
    IN3 (right fwd)  -> GPIO22
    IN4 (right back) -> GPIO23
"""
from gpiozero import Robot

LEFT_FORWARD = 17
LEFT_BACKWARD = 27
RIGHT_FORWARD = 22
RIGHT_BACKWARD = 23

_robot = None
_unavailable = False  # set once GPIO claiming fails, to stop retrying every frame


def _get_robot() -> Robot:
    global _robot
    if _robot is None:
        _robot = Robot(
            left=(LEFT_FORWARD, LEFT_BACKWARD),
            right=(RIGHT_FORWARD, RIGHT_BACKWARD),
        )
    return _robot


def _safe(action) -> None:
    """Run a Robot action. No-ops (with a one-time warning) if the GPIO pins
    can't be claimed, so the rest of the app keeps running."""
    global _unavailable
    if _unavailable:
        return
    try:
        action()
    except Exception as exc:
        _unavailable = True
        print(f"[motors] not available ({exc}) - motor output disabled for this run.")


def go() -> None:
    """Drive forward."""
    _safe(lambda: _get_robot().forward())


def forward() -> None:
    """Drive forward. Alias of go(), used by the manual test controls."""
    go()


def backward() -> None:
    """Drive backward (reverse)."""
    _safe(lambda: _get_robot().backward())


def left() -> None:
    """Turn left: stop the left side, drive the right side forward.

    This is a fixed 4-wheel (non-steering) chassis, not a tank chassis -
    reversing one side to pivot in place binds the wheels, so turns are
    done by stopping one side and driving the other instead."""
    def _do():
        robot = _get_robot()
        robot.left_motor.stop()
        robot.right_motor.forward()
    _safe(_do)


def right() -> None:
    """Turn right: stop the right side, drive the left side forward."""
    def _do():
        robot = _get_robot()
        robot.right_motor.stop()
        robot.left_motor.forward()
    _safe(_do)


def stop() -> None:
    _safe(lambda: _get_robot().stop())


if __name__ == "__main__":
    import time

    print("Driving forward for 1s...")
    go()
    time.sleep(1)
    print("Stopping.")
    stop()
