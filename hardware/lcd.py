"""16x2 I2C LCD status display (PCF8574 backpack) via RPLCD.

Before first use, wire the LCD (VCC->5V, GND->GND, SDA->GPIO2/pin3,
SCL->GPIO3/pin5) then run:
    i2cdetect -l                  # confirm the I2C bus number
    i2cdetect -y <bus>            # confirm the LCD's address (usually 0x27 or 0x3f)
and update I2C_BUS / I2C_ADDRESS below if they differ from the defaults.
"""
from RPLCD.i2c import CharLCD

I2C_BUS = 1  # real GPIO-header I2C bus (bcm2835 @7e804000), enabled via dtparam=i2c_arm=on
I2C_ADDRESS = 0x27

_lcd = None
_unavailable = False  # set once the LCD fails to init/write, to stop retrying every frame


def _get_lcd() -> CharLCD:
    global _lcd
    if _lcd is None:
        _lcd = CharLCD(
            i2c_expander="PCF8574",
            address=I2C_ADDRESS,
            port=I2C_BUS,
            cols=16,
            rows=2,
            dotsize=8,
        )
    return _lcd


def set_status(line1: str, line2: str = "") -> None:
    """Show a status on the LCD. No-ops (with a one-time warning) if the LCD
    isn't wired/reachable yet, so the rest of the app keeps running."""
    global _unavailable
    if _unavailable:
        return
    try:
        lcd = _get_lcd()
        lcd.clear()
        lcd.write_string(line1[:16])
        if line2:
            lcd.cursor_pos = (1, 0)
            lcd.write_string(line2[:16])
    except (OSError, IOError) as exc:
        _unavailable = True
        print(f"[lcd] not reachable ({exc}) - LCD output disabled for this run. "
              f"Check wiring and I2C_BUS/I2C_ADDRESS in hardware/lcd.py.")


if __name__ == "__main__":
    import time

    for text in [("READY", "Smoke test"), ("AWAKE", "Driving"), ("DROWSY!", "STOPPED")]:
        set_status(*text)
        print(f"LCD showing: {text}")
        time.sleep(2)
