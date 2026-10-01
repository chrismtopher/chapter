from __future__ import annotations

import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from abs_kids_player.audio import (
    BOOT_CHIME_SAMPLE_RATE,
    change_volume,
    ensure_boot_chime_wav,
    parse_amixer_volume,
    parse_pactl_muted,
    parse_pactl_volume,
    parse_wpctl_volume,
    toggle_mute,
)


class FakeRunner:
    def __init__(self, stdout: str = "", fail_prefixes: tuple[tuple[str, ...], ...] = ()) -> None:
        self.stdout = stdout
        self.fail_prefixes = fail_prefixes
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        for prefix in self.fail_prefixes:
            if tuple(args[: len(prefix)]) == prefix:
                raise subprocess.CalledProcessError(returncode=1, cmd=args, stderr="not available")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=self.stdout, stderr="")


class AudioTest(unittest.TestCase):
    def test_boot_chime_is_a_short_nonempty_mono_wav(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boot-chime.wav"

            ensure_boot_chime_wav(path)

            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), BOOT_CHIME_SAMPLE_RATE)
                self.assertGreater(wav.getnframes(), BOOT_CHIME_SAMPLE_RATE // 2)
                self.assertLess(wav.getnframes(), BOOT_CHIME_SAMPLE_RATE)
                self.assertTrue(any(wav.readframes(wav.getnframes())))

    def test_parse_amixer_volume_reads_last_percent_and_mute_state(self) -> None:
        output = "Front Left: Playback 65 [65%] [on]\nFront Right: Playback 65 [65%] [off]\n"

        state = parse_amixer_volume(output)

        self.assertEqual(state.percent, 65)
        self.assertTrue(state.muted)

    def test_parse_wpctl_volume_reads_percent_and_mute_state(self) -> None:
        state = parse_wpctl_volume("Volume: 0.42 [MUTED]\n")

        self.assertEqual(state.percent, 42)
        self.assertTrue(state.muted)

    def test_parse_pactl_volume_and_mute(self) -> None:
        state = parse_pactl_volume("Volume: front-left: 49152 / 75% / -8.00 dB\n")

        self.assertEqual(state.percent, 75)
        self.assertTrue(parse_pactl_muted("Mute: yes\n"))

    def test_change_volume_prefers_wpctl(self) -> None:
        runner = FakeRunner("Volume: 0.55\n")

        state = change_volume(2, runner=runner)

        self.assertEqual(
            runner.calls[0],
            ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "10%+"],
        )
        self.assertEqual(state.percent, 55)

    def test_change_volume_falls_back_to_amixer_step_and_unmute(self) -> None:
        runner = FakeRunner(
            "Front Left: Playback 55 [55%] [on]\n",
            fail_prefixes=(("wpctl",), ("pactl",)),
        )

        state = change_volume(2, controls=("Master",), runner=runner)

        self.assertIn(["amixer", "sset", "Master", "10%+", "unmute"], runner.calls)
        self.assertIn(["amixer", "sget", "Master"], runner.calls)
        self.assertEqual(state.percent, 55)

    def test_toggle_mute_falls_back_to_amixer_toggle(self) -> None:
        runner = FakeRunner(
            "Front Left: Playback 50 [50%] [off]\n",
            fail_prefixes=(("wpctl",), ("pactl",)),
        )

        state = toggle_mute(controls=("Master",), runner=runner)

        self.assertIn(["amixer", "sset", "Master", "toggle"], runner.calls)
        self.assertTrue(state.muted)


if __name__ == "__main__":
    unittest.main()
