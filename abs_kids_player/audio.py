from __future__ import annotations

import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]
DEFAULT_MIXER_CONTROLS = ("Master", "PCM", "Headphone", "Speaker")
VOLUME_STEP_PERCENT = 5
CONTROL_CLICK_WAV_PATH = Path("/tmp/chapter-control-click-v2.wav")
CONTROL_CLICK_SAMPLE_RATE = 16000
CONTROL_CLICK_SECONDS = 0.018
CONTROL_CLICK_FREQUENCY_HZ = 1150
CONTROL_CLICK_MAX_PERCENT = 18
BOOT_CHIME_WAV_PATH = Path("/tmp/chapter-boot-chime-v2.wav")
BOOT_CHIME_SAMPLE_RATE = 24000
BOOT_CHIME_VOICES = (
    (0.000, 0.20, 523.25, 0.72),
    (0.085, 0.20, 659.25, 0.76),
    (0.170, 0.22, 783.99, 0.80),
    (0.265, 0.22, 987.77, 0.82),
    (0.360, 0.34, 1046.50, 1.00),
    (0.455, 0.22, 1318.51, 0.42),
)


class AudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class VolumeState:
    percent: int
    muted: bool = False


def run_command(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, check=True, text=True)


def get_volume(
    controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    runner: CommandRunner = run_command,
) -> VolumeState:
    last_error: Exception | None = None
    for reader in (
        lambda: get_wpctl_volume(runner),
        lambda: get_pactl_volume(runner),
        lambda: get_amixer_volume(controls, runner),
    ):
        try:
            return reader()
        except (subprocess.CalledProcessError, AudioError, FileNotFoundError) as error:
            last_error = error
    raise AudioError(f"Could not read system volume: {last_error}")


def change_volume(
    steps: int,
    controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    runner: CommandRunner = run_command,
) -> VolumeState:
    if steps == 0:
        return get_volume(controls, runner)

    last_error: Exception | None = None
    for writer in (
        lambda: change_wpctl_volume(steps, runner),
        lambda: change_pactl_volume(steps, runner),
        lambda: change_amixer_volume(steps, controls, runner),
    ):
        try:
            return writer()
        except (subprocess.CalledProcessError, AudioError, FileNotFoundError) as error:
            last_error = error
    raise AudioError(f"Could not control system volume: {last_error}")


def toggle_mute(
    controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    runner: CommandRunner = run_command,
) -> VolumeState:
    last_error: Exception | None = None
    for writer in (
        lambda: toggle_wpctl_mute(runner),
        lambda: toggle_pactl_mute(runner),
        lambda: toggle_amixer_mute(controls, runner),
    ):
        try:
            return writer()
        except (subprocess.CalledProcessError, AudioError, FileNotFoundError) as error:
            last_error = error
    raise AudioError(f"Could not toggle mute: {last_error}")


def play_control_click(percent: int = 12) -> None:
    ensure_control_click_wav()
    volume = max(0, min(percent, CONTROL_CLICK_MAX_PERCENT))
    if volume <= 0:
        return
    try:
        subprocess.Popen(
            ["aplay", "-q", str(CONTROL_CLICK_WAV_PATH)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return


def ensure_control_click_wav(path: Path = CONTROL_CLICK_WAV_PATH) -> None:
    if path.exists():
        return

    frames = bytearray()
    sample_count = max(1, round(CONTROL_CLICK_SAMPLE_RATE * CONTROL_CLICK_SECONDS))
    for index in range(sample_count):
        progress = index / sample_count
        attack = min(1.0, progress / 0.18)
        envelope = attack * (1.0 - progress) ** 4
        wave_value = math.sin(2 * math.pi * CONTROL_CLICK_FREQUENCY_HZ * index / CONTROL_CLICK_SAMPLE_RATE)
        sample = round(wave_value * envelope * 32767 * 0.13)
        frames.extend(sample.to_bytes(2, byteorder="little", signed=True))

    try:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(CONTROL_CLICK_SAMPLE_RATE)
            wav.writeframes(bytes(frames))
    except OSError:
        return


def play_boot_chime() -> None:
    ensure_boot_chime_wav()
    try:
        subprocess.Popen(
            ["aplay", "-q", str(BOOT_CHIME_WAV_PATH)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return


def ensure_boot_chime_wav(path: Path = BOOT_CHIME_WAV_PATH) -> None:
    if path.exists():
        return

    frames = bytearray()
    chime_seconds = max(start + duration for start, duration, _frequency, _level in BOOT_CHIME_VOICES)
    sample_count = max(1, round(BOOT_CHIME_SAMPLE_RATE * chime_seconds))
    for index in range(sample_count):
        elapsed = index / BOOT_CHIME_SAMPLE_RATE
        mixed = 0.0
        for start, duration, frequency_hz, level in BOOT_CHIME_VOICES:
            note_elapsed = elapsed - start
            if note_elapsed < 0 or note_elapsed >= duration:
                continue
            remaining = duration - note_elapsed
            attack = min(1.0, note_elapsed / 0.010)
            release = min(1.0, remaining / 0.075)
            envelope = min(attack, release)
            phase = 2 * math.pi * frequency_hz * note_elapsed
            tone = math.sin(phase) + 0.14 * math.sin(phase * 2)
            mixed += (tone / 1.14) * envelope * level
        sample = round(math.tanh(mixed * 0.72) * 32767 * 0.13)
        frames.extend(sample.to_bytes(2, byteorder="little", signed=True))

    try:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(BOOT_CHIME_SAMPLE_RATE)
            wav.writeframes(bytes(frames))
    except OSError:
        return


def get_wpctl_volume(runner: CommandRunner = run_command) -> VolumeState:
    result = runner(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    return parse_wpctl_volume(result.stdout)


def change_wpctl_volume(steps: int, runner: CommandRunner = run_command) -> VolumeState:
    operator = "+" if steps > 0 else "-"
    amount = abs(steps) * VOLUME_STEP_PERCENT
    runner(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{amount}%{operator}"])
    runner(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
    return get_wpctl_volume(runner)


def toggle_wpctl_mute(runner: CommandRunner = run_command) -> VolumeState:
    runner(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
    return get_wpctl_volume(runner)


def parse_wpctl_volume(output: str) -> VolumeState:
    match = re.search(r"Volume:\s+([0-9]+(?:\.[0-9]+)?)", output)
    if not match:
        raise AudioError("wpctl output did not include a volume value.")
    muted = "[MUTED]" in output.upper()
    return VolumeState(percent=clamp(round(float(match.group(1)) * 100), 0, 100), muted=muted)


def get_pactl_volume(runner: CommandRunner = run_command) -> VolumeState:
    volume = runner(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    mute = runner(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
    state = parse_pactl_volume(volume.stdout)
    return VolumeState(percent=state.percent, muted=parse_pactl_muted(mute.stdout))


def change_pactl_volume(steps: int, runner: CommandRunner = run_command) -> VolumeState:
    operator = "+" if steps > 0 else "-"
    amount = abs(steps) * VOLUME_STEP_PERCENT
    runner(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{operator}{amount}%"])
    runner(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
    return get_pactl_volume(runner)


def toggle_pactl_mute(runner: CommandRunner = run_command) -> VolumeState:
    runner(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
    return get_pactl_volume(runner)


def parse_pactl_volume(output: str) -> VolumeState:
    percents = [int(match) for match in re.findall(r"(\d{1,3})%", output)]
    if not percents:
        raise AudioError("pactl output did not include a volume percentage.")
    return VolumeState(percent=clamp(percents[0], 0, 100))


def parse_pactl_muted(output: str) -> bool:
    return "yes" in output.lower()


def get_amixer_volume(
    controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    runner: CommandRunner = run_command,
) -> VolumeState:
    for control in controls:
        try:
            result = runner(["amixer", "sget", control])
            return parse_amixer_volume(result.stdout)
        except (subprocess.CalledProcessError, AudioError, FileNotFoundError):
            continue
    raise AudioError(f"Could not read ALSA controls: {', '.join(controls)}")


def change_amixer_volume(
    steps: int,
    controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    runner: CommandRunner = run_command,
) -> VolumeState:
    operator = "+" if steps > 0 else "-"
    amount = abs(steps) * VOLUME_STEP_PERCENT
    run_first_working_amixer_control(["sset", "{control}", f"{amount}%{operator}", "unmute"], controls, runner)
    return get_amixer_volume(controls, runner)


def toggle_amixer_mute(
    controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    runner: CommandRunner = run_command,
) -> VolumeState:
    run_first_working_amixer_control(["sset", "{control}", "toggle"], controls, runner)
    return get_amixer_volume(controls, runner)


def run_first_working_amixer_control(
    args_template: list[str],
    controls: tuple[str, ...],
    runner: CommandRunner,
) -> None:
    last_error: Exception | None = None
    for control in controls:
        args = ["amixer", *[part.format(control=control) for part in args_template]]
        try:
            runner(args)
            return
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            last_error = error
    raise AudioError(f"Could not control ALSA volume: {last_error}")


def parse_amixer_volume(output: str) -> VolumeState:
    percents = [int(match) for match in re.findall(r"\[(\d{1,3})%\]", output)]
    if not percents:
        raise AudioError("amixer output did not include a volume percentage.")
    muted = "[off]" in output
    return VolumeState(percent=clamp(percents[-1], 0, 100), muted=muted)


def clamp(value: int, minimum: int, maximum: int) -> int:
    return min(max(value, minimum), maximum)
