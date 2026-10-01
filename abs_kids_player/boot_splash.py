from __future__ import annotations

import argparse
import time
import zlib
from pathlib import Path


CHAPTER_SPLASH_PACKED = zlib.decompress(
    bytes.fromhex(
        "78daed96bd4a03411080e72489241a387d0035a585904eedd2292231b54d528b90bc41e213187c0105b53620885824165682d1569b4b21164238124ca2f9b971e7768f8340ba8dbff335cbde2dfbedcdccee1e00c3300cc3300cf353b1b0c4fe1164b1c9fe3febdfb6061726f937ecd7b8e8af57b17e22da28f68265e700e00c05038050191fe372a98bb6b66a4dd2ec4762d25bd1be0144a84fc188629fcc09cf1fb445d375fde7b6b6dd1244cf4f389ebf4b7e97a6e74fab9162e81d6af3cf211e1bcb4531a9935a428c43f834666c229ae47f360eb1a7f26f20beccec639bfcb8172868f2e7f143d55f0b028819b7338198227f02a66925ae7f929e45a80e2c7cd7577d156c287f8db43980d52ac53927fc221b215a84eb9f52dd0531b4a173dfd5547b4d21ce4158a69dfc7d902171fdaa1cc4722c7c1887bf24fd59a9298cf2a7f45e157efc95bf826dd390fea1f84b327afd7efd293f252224fd5efda565fd39e3b82addfdb752f4fdf7d832b2caaff6df1615bc787963ceae5d69f6fbe78ff2e7fdfcabf307e645d351e74f4ff7af4272c84f79eea8fa93e7afbb253af2fcd5ef871deffe917ed8c5a798f4abfb871e093fdd3ff5cbc497fd2a45e95bbf11f6ff6f3fc3300cc3300cf3dbf804b3c7d4d3"
    )
)


class SplashFrame:
    def __init__(self, text: str) -> None:
        self.text = text


class BootSplashDisplay:
    def __init__(
        self,
        spi_bus: int = 0,
        spi_device: int = 0,
        dc_pin: int = 24,
        reset_pin: int = 25,
        max_speed_hz: int = 1_000_000,
    ) -> None:
        import lgpio
        import spidev

        self._lgpio = lgpio
        self._gpio_handle: int | None = None
        self.spi = spidev.SpiDev()
        try:
            self.spi.open(spi_bus, spi_device)
            self.spi.max_speed_hz = max_speed_hz
            self.spi.mode = 0
            self._gpio_handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self._gpio_handle, 0, dc_pin, 0)
            lgpio.gpio_claim_output(self._gpio_handle, 0, reset_pin, 1)
            self.dc_pin = dc_pin
            self.reset_pin = reset_pin
            self.reset_display()
            self.init_display()
        except Exception:
            self.release_gpio()
            self.spi.close()
            raise

    def write_gpio(self, pin: int, value: int) -> None:
        if self._gpio_handle is None:
            return
        self._lgpio.gpio_write(self._gpio_handle, pin, value)

    def reset_display(self) -> None:
        self.write_gpio(self.reset_pin, 1)
        time.sleep(0.001)
        self.write_gpio(self.reset_pin, 0)
        time.sleep(0.01)
        self.write_gpio(self.reset_pin, 1)
        time.sleep(0.01)

    def init_display(self) -> None:
        self.command(
            [
                0xAE,
                0x00,
                0x10,
                0x40,
                0xA0,
                0xA8,
                63,
                0xC0,
                0xD3,
                0x00,
                0x81,
                0x80,
                0xA4,
                0xA6,
                0xAF,
            ]
        )

    def command(self, values: list[int]) -> None:
        self.write_gpio(self.dc_pin, 0)
        self.spi.xfer2(values)

    def data(self, values: bytes) -> None:
        self.write_gpio(self.dc_pin, 1)
        for index in range(0, len(values), 4096):
            self.spi.xfer2(list(values[index : index + 4096]))

    def show(self, _frame: SplashFrame) -> None:
        self.command([0x00, 0x10, 0xB0])
        self.data(CHAPTER_SPLASH_PACKED)

    def release_gpio(self) -> None:
        if self._gpio_handle is None:
            return
        try:
            self._lgpio.gpiochip_close(self._gpio_handle)
        finally:
            self._gpio_handle = None


Sh1122Display = BootSplashDisplay


def show_boot_splash(
    spi_bus: int = 0,
    spi_device: int = 0,
    dc_pin: int = 24,
    reset_pin: int = 25,
    speed: int = 1_000_000,
    hold_seconds: float = 0.25,
    handoff_path: str = "",
    max_hold_seconds: float = 45.0,
    poll_seconds: float = 0.1,
    startup_timeout_seconds: float = 5.0,
    startup_poll_seconds: float = 0.05,
) -> None:
    display = open_display(
        spi_bus,
        spi_device,
        dc_pin,
        reset_pin,
        speed,
        startup_timeout_seconds,
        startup_poll_seconds,
    )
    display.show(SplashFrame("chapter"))
    if handoff_path:
        wait_for_handoff(Path(handoff_path), max_hold_seconds, poll_seconds)
    elif hold_seconds > 0:
        time.sleep(hold_seconds)
    # Intentionally do not call display.close(): it sends display-off.
    display.spi.close()
    release_gpio = getattr(display, "release_gpio", None)
    if release_gpio is not None:
        release_gpio()


def open_display(
    spi_bus: int,
    spi_device: int,
    dc_pin: int,
    reset_pin: int,
    speed: int,
    timeout_seconds: float,
    poll_seconds: float,
) -> Sh1122Display:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            return Sh1122Display(
                spi_bus=spi_bus,
                spi_device=spi_device,
                dc_pin=dc_pin,
                reset_pin=reset_pin,
                max_speed_hz=speed,
            )
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(max(0.01, poll_seconds))


def wait_for_handoff(path: Path, max_hold_seconds: float, poll_seconds: float = 0.1) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

    deadline = time.monotonic() + max(0.0, max_hold_seconds)
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(min(max(0.01, poll_seconds), max(0.0, deadline - time.monotonic())))


def main() -> None:
    parser = argparse.ArgumentParser(description="Show the Chapter boot splash on the OLED.")
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--dc-pin", type=int, default=24)
    parser.add_argument("--reset-pin", type=int, default=25)
    parser.add_argument("--speed", type=int, default=1_000_000)
    parser.add_argument("--hold-seconds", type=float, default=0.25)
    parser.add_argument("--handoff-path", default="")
    parser.add_argument("--max-hold-seconds", type=float, default=45.0)
    parser.add_argument("--poll-seconds", type=float, default=0.1)
    parser.add_argument("--startup-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--startup-poll-seconds", type=float, default=0.05)
    args = parser.parse_args()
    show_boot_splash(
        spi_bus=args.spi_bus,
        spi_device=args.spi_device,
        dc_pin=args.dc_pin,
        reset_pin=args.reset_pin,
        speed=args.speed,
        hold_seconds=args.hold_seconds,
        handoff_path=args.handoff_path,
        max_hold_seconds=args.max_hold_seconds,
        poll_seconds=args.poll_seconds,
        startup_timeout_seconds=args.startup_timeout_seconds,
        startup_poll_seconds=args.startup_poll_seconds,
    )


if __name__ == "__main__":
    main()
