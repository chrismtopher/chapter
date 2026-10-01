from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abs_kids_player.boot_splash import CHAPTER_SPLASH_PACKED, open_display, show_boot_splash


class FakeSpi:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeDisplay:
    instances: list["FakeDisplay"] = []

    def __init__(self, **_kwargs) -> None:
        self.frames = []
        self.closed = False
        self.spi = FakeSpi()
        FakeDisplay.instances.append(self)

    def show(self, frame) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


class BootSplashTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeDisplay.instances = []

    def test_boot_splash_leaves_display_on(self) -> None:
        with patch("abs_kids_player.boot_splash.Sh1122Display", FakeDisplay):
            show_boot_splash(hold_seconds=0)

        display = FakeDisplay.instances[0]
        self.assertEqual(display.frames[0].text, "chapter")
        self.assertTrue(display.spi.closed)
        self.assertFalse(display.closed)

    def test_pre_rendered_splash_matches_full_display_frame_size(self) -> None:
        self.assertEqual(len(CHAPTER_SPLASH_PACKED), 256 * 64 // 2)

    def test_boot_splash_waits_for_handoff_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory) / "handoff"

            def create_handoff_marker(_seconds: float) -> None:
                handoff.write_text("starting\n", encoding="utf-8")

            with (
                patch("abs_kids_player.boot_splash.Sh1122Display", FakeDisplay),
                patch("abs_kids_player.boot_splash.time.sleep", create_handoff_marker),
            ):
                show_boot_splash(
                    hold_seconds=0,
                    handoff_path=str(handoff),
                    max_hold_seconds=1,
                    poll_seconds=0.01,
                )

        display = FakeDisplay.instances[0]
        self.assertEqual(display.frames[0].text, "chapter")
        self.assertTrue(display.spi.closed)
        self.assertFalse(display.closed)

    def test_open_display_retries_until_spi_is_ready(self) -> None:
        attempts = 0

        def create_display(**_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise FileNotFoundError("SPI is not ready")
            return FakeDisplay()

        with (
            patch("abs_kids_player.boot_splash.Sh1122Display", create_display),
            patch("abs_kids_player.boot_splash.time.sleep") as sleep,
        ):
            display = open_display(0, 0, 24, 25, 1_000_000, timeout_seconds=1, poll_seconds=0.05)

        self.assertIsInstance(display, FakeDisplay)
        self.assertEqual(attempts, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
