from __future__ import annotations

import argparse
import time

from .appliance_io import Sh1122Display
from .rotary_ui import TwoLineFrame, WifiSetupFrame
from .wifi import SETUP_HOTSPOT_SSID, SETUP_HOTSPOT_URL


def main() -> None:
    parser = argparse.ArgumentParser(description="Show a simple test pattern on the SH1122 OLED.")
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--dc-pin", type=int, default=24)
    parser.add_argument("--reset-pin", type=int, default=25)
    parser.add_argument("--cs-pin", type=int, default=None)
    parser.add_argument("--speed", type=int, default=1_000_000)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument(
        "--skip-all-on",
        action="store_true",
        help="Skip the controller all-pixels-on check.",
    )
    args = parser.parse_args()

    display = Sh1122Display(
        spi_bus=args.spi_bus,
        spi_device=args.spi_device,
        dc_pin=args.dc_pin,
        reset_pin=args.reset_pin,
        cs_pin=args.cs_pin,
        max_speed_hz=args.speed,
    )
    try:
        if not args.skip_all_on:
            display.command([0xA5])
            time.sleep(1)
            display.command([0xA4])

        deadline = time.monotonic() + args.seconds
        frames = [
            TwoLineFrame("OLED test", "SH1122 SPI OK"),
            WifiSetupFrame(SETUP_HOTSPOT_SSID, SETUP_HOTSPOT_URL),
            TwoLineFrame("Pins", "DC24 RST25 CS8"),
        ]
        index = 0
        while time.monotonic() < deadline:
            display.show(frames[index % len(frames)])
            index += 1
            time.sleep(1)
    finally:
        display.close()


if __name__ == "__main__":
    main()
