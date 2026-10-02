from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable


DuckCallback = Callable[[bool], None]
ProcessFactory = Callable[..., subprocess.Popen]

ESPEAK_VOICE = "en-us"
ESPEAK_SPEED_WPM = 150
ESPEAK_PITCH = 50


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    due_at: float
    volume_percent: int


class SpokenNavigationFeedback:
    def __init__(
        self,
        duck_callback: DuckCallback | None = None,
        process_factory: ProcessFactory = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.duck_callback = duck_callback
        self.process_factory = process_factory
        self.clock = clock
        self.pending: SpeechRequest | None = None
        self.speech_process: subprocess.Popen | None = None
        self.audio_process: subprocess.Popen | None = None
        self.ducked = False
        self.unavailable_reported = False

    def request(
        self,
        text: str,
        delay_seconds: float = 0.0,
        volume_percent: int = 50,
        muted: bool = False,
    ) -> None:
        clean_text = " ".join(text.split())
        self.stop_processes()
        if not clean_text or muted or volume_percent <= 0:
            self.pending = None
            self.set_ducked(False)
            return
        self.pending = SpeechRequest(
            text=clean_text,
            due_at=self.clock() + max(0.0, delay_seconds),
            volume_percent=min(max(volume_percent, 1), 100),
        )

    def poll(self, output_device: str = "") -> None:
        if self.audio_process is not None and self.audio_process.poll() is not None:
            self.stop_processes()
        if self.pending is not None and self.clock() >= self.pending.due_at:
            request = self.pending
            self.pending = None
            self.start(request, output_device)
        if self.pending is None and self.audio_process is None:
            self.set_ducked(False)

    @property
    def ready_to_start(self) -> bool:
        return self.pending is not None and self.clock() >= self.pending.due_at

    def start(self, request: SpeechRequest, output_device: str) -> None:
        if not shutil.which("espeak-ng") or not shutil.which("aplay"):
            if not self.unavailable_reported:
                print("Spoken navigation unavailable: install espeak-ng and alsa-utils")
                self.unavailable_reported = True
            self.set_ducked(False)
            return

        amplitude = min(200, max(1, request.volume_percent * 2))
        self.set_ducked(True)
        try:
            self.speech_process = self.process_factory(
                [
                    "espeak-ng",
                    "--stdout",
                    "-z",
                    "-v",
                    ESPEAK_VOICE,
                    "-s",
                    str(ESPEAK_SPEED_WPM),
                    "-p",
                    str(ESPEAK_PITCH),
                    "-a",
                    str(amplitude),
                    request.text,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            audio_command = ["aplay", "-q"]
            if output_device:
                audio_command.extend(["-D", output_device])
            self.audio_process = self.process_factory(
                audio_command,
                stdin=self.speech_process.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if self.speech_process.stdout is not None:
                self.speech_process.stdout.close()
        except (FileNotFoundError, OSError) as error:
            print(f"Spoken navigation failed: {error}")
            self.stop_processes()
            self.set_ducked(False)

    def cancel(self) -> None:
        self.pending = None
        self.stop_processes()
        self.set_ducked(False)

    def close(self) -> None:
        self.cancel()

    def stop_processes(self) -> None:
        for process in (self.audio_process, self.speech_process):
            if process is None or process.poll() is not None:
                continue
            try:
                process.terminate()
            except OSError:
                pass
        self.audio_process = None
        self.speech_process = None

    def set_ducked(self, ducked: bool) -> None:
        if self.ducked == ducked:
            return
        self.ducked = ducked
        if self.duck_callback is not None:
            try:
                self.duck_callback(ducked)
            except Exception as error:
                print(f"Spoken navigation ducking failed: {error}")
