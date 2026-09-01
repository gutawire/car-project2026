"""Raw I2C diagnostic: scans bus 1 (the GPIO header bus) directly via smbus2,
independent of RPLCD, to pinpoint whether the LCD is actually responding.
Run: python hardware/i2c_test.py
"""
from smbus2 import SMBus, i2c_msg

BUS = 1
COMMON_LCD_ADDRESSES = [0x20, 0x27, 0x38, 0x3f]


def probe(bus: SMBus, address: int) -> bool:
    """Try a zero-length write (the same trick i2cdetect uses) to see if
    anything on the bus ACKs this address."""
    try:
        bus.i2c_rdwr(i2c_msg.write(address, []))
        return True
    except OSError:
        return False


def main() -> None:
    print(f"Opening /dev/i2c-{BUS} ...")
    try:
        bus = SMBus(BUS)
    except FileNotFoundError as exc:
        print(f"FAILED to open bus {BUS}: {exc}")
        print("Check that dtparam=i2c_arm=on is set in /boot/firmware/config.txt and the Pi was rebooted.")
        return

    print(f"Bus {BUS} opened OK. Scanning full address range 0x03-0x77 ...")
    found = []
    for addr in range(0x03, 0x78):
        if probe(bus, addr):
            found.append(addr)

    if found:
        print(f"FOUND {len(found)} device(s) at: {[hex(a) for a in found]}")
    else:
        print("FOUND: nothing. No device ACKed on any address.")
        print("This means the Pi is getting zero response on SDA/SCL -- a wiring")
        print("problem (bad connection, wrong pins, or the module isn't in I2C mode),")
        print("not a config/address problem.")

    print()
    print("Explicit probe of common LCD backpack addresses:")
    for addr in COMMON_LCD_ADDRESSES:
        ok = probe(bus, addr)
        print(f"  {hex(addr)}: {'RESPONDING' if ok else 'no response'}")

    bus.close()


if __name__ == "__main__":
    main()
