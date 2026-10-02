from __future__ import annotations

import threading
import time
from typing import Any

from .api import AudiobookshelfClient, AudiobookshelfError
from .bluetooth_audio import preferred_bluetooth_alsa_device
from .models import PlaybackSession


PROGRESS_SYNC_SECONDS = 15
VOLUME_FADE_SECONDS = 0.35
VOLUME_FADE_STEPS = 16
PREROLL_VOLUME_FLOOR = 0.001
SILENCE_VOLUME = 0.0
MAX_EFFECTIVE_VOLUME = 1.0
SPOKEN_NAVIGATION_DUCK_FACTOR = 0.18
PLAY_START_SETTLE_SECONDS = 0.20
RESUME_SETTLE_SECONDS = 0.20
STATE_CHANGE_TIMEOUT_SECONDS = 5
SMART_RESUME_SHORT_PAUSE_SECONDS = 10.0
SMART_RESUME_LONG_PAUSE_SECONDS = 300.0
SMART_RESUME_MEDIUM_REWIND_SECONDS = 3.0
SMART_RESUME_LONG_REWIND_SECONDS = 8.0


class PlaybackError(RuntimeError):
    pass


class GStreamerPlayback:
    def __init__(self) -> None:
        self.Gst: Any | None = None
        self.playbin: Any | None = None
        self.session: PlaybackSession | None = None
        self.client: AudiobookshelfClient | None = None
        self.track_index = 0
        self.current_time = 0.0
        self.is_playing = False
        self.last_sync = 0.0
        self.volume_percent = 50
        self.muted = False
        self.soft_paused = False
        self.soft_pause_time = 0.0
        self.soft_paused_at = 0.0
        self.spoken_navigation_ducked = False
        self._sync_lock = threading.Lock()
        self._sync_in_flight = False
        self._audio_lock = threading.Lock()
        self._effective_volume = 0.5
        self.bluetooth_output_enabled = False
        self.audio_output_device = ""

    def start(self, session: PlaybackSession, client: AudiobookshelfClient) -> None:
        self.stop()
        self.Gst = load_gstreamer()
        self.playbin = self.Gst.ElementFactory.make("playbin", "chapter-player")
        if self.playbin is None:
            raise PlaybackError("Could not create GStreamer playbin.")
        self.session = session
        self.client = client
        self.track_index = self.track_index_for_time(session.current_time)
        self.current_time = session.current_time
        self.soft_paused = False
        self.soft_pause_time = 0.0
        self.soft_paused_at = 0.0
        self.spoken_navigation_ducked = False
        self.set_output_volume(PREROLL_VOLUME_FLOOR)
        self.load_current_track(apply_audio=False)
        self.set_output_volume(PREROLL_VOLUME_FLOOR)
        self.playbin.set_state(self.Gst.State.PLAYING)
        self.is_playing = True
        time.sleep(PLAY_START_SETTLE_SECONDS)
        self.apply_audio_state()
        self.last_sync = time.monotonic()

    def stop(self) -> None:
        if self.playbin is not None and self.Gst is not None:
            self.playbin.set_state(self.Gst.State.NULL)
        self.playbin = None
        self.session = None
        self.client = None
        self.audio_output_device = ""
        self.current_time = 0.0
        self.is_playing = False
        self.soft_paused = False
        self.soft_pause_time = 0.0
        self.soft_paused_at = 0.0
        self.spoken_navigation_ducked = False

    def toggle(self) -> None:
        if self.playbin is None or self.Gst is None:
            return
        if self.is_playing:
            self.pause()
            return
        self.resume()

    def resume(self, sync: bool = False, percent: int | None = None, muted: bool | None = None) -> None:
        if self.playbin is None or self.Gst is None:
            return
        if percent is not None:
            self.volume_percent = clamp(percent, 0, 100)
        if muted is not None:
            self.muted = muted or self.volume_percent <= 0
        resume_time = self.smart_resume_time() if self.soft_paused else None
        self.set_output_volume(PREROLL_VOLUME_FLOOR)
        if resume_time is not None:
            self.seek_without_sync(resume_time)
        self.soft_paused = False
        self.soft_pause_time = 0.0
        self.soft_paused_at = 0.0
        self.playbin.set_state(self.Gst.State.PLAYING)
        self.is_playing = True
        if resume_time is not None:
            time.sleep(RESUME_SETTLE_SECONDS)
        self.apply_audio_state()
        if sync:
            self.request_progress_sync()

    def pause(self, sync: bool = True, keep_audio_alive: bool = True) -> None:
        if self.playbin is None or self.Gst is None:
            return
        self.is_playing = False
        if keep_audio_alive:
            self.soft_paused = True
            self.soft_pause_time = self.current_time
            self.soft_paused_at = time.monotonic()
            self.apply_audio_state()
            if sync:
                self.request_progress_sync()
            return
        self.soft_paused = False
        self.soft_pause_time = 0.0
        self.soft_paused_at = 0.0
        self.playbin.set_state(self.Gst.State.PAUSED)
        if sync:
            self.request_progress_sync()

    def seek_global(self, current_time: float) -> None:
        if self.session is None or self.playbin is None or self.Gst is None:
            return
        self.current_time = min(max(current_time, 0), self.session.duration)
        if self.soft_paused:
            self.soft_pause_time = self.current_time
            self.soft_paused_at = time.monotonic()
        new_index = self.track_index_for_time(self.current_time)
        if new_index != self.track_index:
            was_playing = self.is_playing
            self.track_index = new_index
            self.load_current_track()
            self.playbin.set_state(self.Gst.State.PLAYING if was_playing else self.Gst.State.PAUSED)
        else:
            self.seek_track(self.current_time - self.current_track.start_offset)
        self.request_progress_sync()

    def seek_without_sync(self, current_time: float) -> None:
        if self.session is None or self.playbin is None or self.Gst is None:
            return
        self.current_time = min(max(current_time, 0), self.session.duration)
        new_index = self.track_index_for_time(self.current_time)
        if new_index != self.track_index:
            self.track_index = new_index
            self.load_current_track()
            return
        self.seek_track(self.current_time - self.current_track.start_offset)

    def smart_resume_time(self) -> float:
        rewind = smart_resume_rewind_seconds(time.monotonic() - self.soft_paused_at)
        return max(0.0, self.soft_pause_time - rewind)

    def poll(self) -> None:
        if self.playbin is None or self.Gst is None:
            return
        if not self.is_playing:
            return
        self.handle_bus_messages()
        if self.playbin is None or self.session is None or not self.is_playing:
            return
        success, position = self.playbin.query_position(self.Gst.Format.TIME)
        if success and self.session is not None:
            self.current_time = self.current_track.start_offset + position / self.Gst.SECOND
        if self.is_playing and time.monotonic() - self.last_sync >= PROGRESS_SYNC_SECONDS:
            self.request_progress_sync()
            self.last_sync = time.monotonic()

    @property
    def current_track(self):
        if self.session is None:
            raise PlaybackError("No playback session is active.")
        return self.session.tracks[self.track_index]

    def track_index_for_time(self, current_time: float) -> int:
        if self.session is None:
            return 0
        for index, track in enumerate(self.session.tracks):
            if track.start_offset <= current_time < track.start_offset + track.duration:
                return index
        return max(0, len(self.session.tracks) - 1)

    def load_current_track(self, apply_audio: bool = True) -> None:
        if self.playbin is None or self.Gst is None:
            return
        track = self.current_track
        if isinstance(self.client, AudiobookshelfClient):
            try:
                track.url = self.client.authenticated_media_url(track.url)
            except AudiobookshelfError as error:
                raise PlaybackError(str(error)) from error
        self.playbin.set_state(self.Gst.State.NULL)
        self.configure_audio_sink()
        self.playbin.set_property("uri", track.url)
        if apply_audio:
            self.apply_audio_state()
        self.playbin.set_state(self.Gst.State.PAUSED)
        self.wait_for_state_change()
        self.seek_track(max(0, self.current_time - track.start_offset))
        self.wait_for_state_change()

    def seek_track(self, seconds: float) -> None:
        if self.playbin is None or self.Gst is None:
            return
        ok = self.playbin.seek_simple(
            self.Gst.Format.TIME,
            self.Gst.SeekFlags.FLUSH | self.Gst.SeekFlags.KEY_UNIT,
            int(seconds * self.Gst.SECOND),
        )
        if ok is False:
            print(f"GStreamer seek failed at {seconds:.1f}s")

    def wait_for_state_change(self) -> None:
        if self.playbin is None or self.Gst is None or not hasattr(self.playbin, "get_state"):
            return
        try:
            self.playbin.get_state(int(STATE_CHANGE_TIMEOUT_SECONDS * self.Gst.SECOND))
        except Exception as error:
            print(f"GStreamer state wait failed: {error}")

    def configure_audio_sink(self) -> None:
        if self.playbin is None or self.Gst is None:
            return

        if not self.bluetooth_output_enabled:
            self.select_default_audio_sink()
            return

        device = preferred_bluetooth_alsa_device()
        if not device:
            self.select_default_audio_sink()
            return

        try:
            sink = self.Gst.ElementFactory.make("alsasink", "chapter-bluetooth-sink")
            if sink is None:
                print("GStreamer alsasink is unavailable; using default speaker output.")
                self.audio_output_device = ""
                return
            sink.set_property("device", device)
            self.playbin.set_property("audio-sink", sink)
            self.audio_output_device = device
            print(f"Bluetooth audio output selected: {device}")
        except Exception as error:
            self.audio_output_device = ""
            print(f"Bluetooth audio output could not be selected: {error}")

    def select_default_audio_sink(self) -> None:
        self.audio_output_device = ""
        if self.playbin is None:
            return
        try:
            self.playbin.set_property("audio-sink", None)
        except Exception as error:
            print(f"GStreamer default audio sink could not be selected: {error}")

    def set_bluetooth_output_enabled(self, enabled: bool) -> None:
        self.bluetooth_output_enabled = enabled

    def refresh_audio_output(self) -> None:
        if self.session is None or self.playbin is None or self.Gst is None:
            return
        was_playing = self.is_playing
        self.set_output_volume(PREROLL_VOLUME_FLOOR)
        self.load_current_track(apply_audio=False)
        self.playbin.set_state(self.Gst.State.PLAYING if was_playing else self.Gst.State.PAUSED)
        if was_playing:
            time.sleep(RESUME_SETTLE_SECONDS)
        self.apply_audio_state()

    def advance_within_session(self) -> bool:
        if self.session is None or self.playbin is None or self.Gst is None:
            return False
        if self.track_index + 1 >= len(self.session.tracks):
            self.current_time = self.session.duration
            self.request_progress_sync()
            self.stop()
            return False
        self.track_index += 1
        self.current_time = self.current_track.start_offset
        self.load_current_track()
        self.playbin.set_state(self.Gst.State.PLAYING)
        self.is_playing = True
        return True

    def handle_bus_messages(self) -> None:
        if self.playbin is None or self.Gst is None:
            return
        bus = self.playbin.get_bus()
        while True:
            message = bus.timed_pop_filtered(0, self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS)
            if message is None:
                return
            if message.type == self.Gst.MessageType.EOS:
                if not self.advance_within_session():
                    return
            elif message.type == self.Gst.MessageType.ERROR:
                self.stop()
                raise PlaybackError("GStreamer playback error.")

    def sync_progress(self) -> None:
        if self.client is None or self.session is None:
            return
        try:
            self.client.update_progress(
                self.session.library_item_id,
                self.current_time,
                self.session.duration,
                session_id=self.session.id,
                time_listened=self.time_listened_since_last_sync(),
            )
            self.last_sync = time.monotonic()
        except AudiobookshelfError as error:
            print(f"Progress sync failed: {error}")

    def request_progress_sync(self) -> None:
        if self.client is None or self.session is None:
            return
        client = self.client
        session_id = self.session.id
        item_id = self.session.library_item_id
        current_time = self.current_time
        duration = self.session.duration
        time_listened = self.time_listened_since_last_sync()
        with self._sync_lock:
            if self._sync_in_flight:
                return
            self._sync_in_flight = True
            self.last_sync = time.monotonic()

        def run_sync() -> None:
            try:
                client.update_progress(
                    item_id,
                    current_time,
                    duration,
                    session_id=session_id,
                    time_listened=time_listened,
                )
            except Exception as error:
                print(f"Progress sync failed: {error}")
            finally:
                with self._sync_lock:
                    self._sync_in_flight = False

        threading.Thread(target=run_sync, daemon=True).start()

    def time_listened_since_last_sync(self) -> float:
        if not self.is_playing:
            return 0.0
        return max(0.0, time.monotonic() - self.last_sync)

    def set_volume_state(self, percent: int, muted: bool) -> None:
        self.volume_percent = clamp(percent, 0, 100)
        self.muted = muted or self.volume_percent <= 0
        self.apply_audio_state()

    def set_spoken_navigation_ducked(self, ducked: bool) -> None:
        if self.spoken_navigation_ducked == ducked:
            return
        self.spoken_navigation_ducked = ducked
        self.apply_audio_state()

    def apply_audio_state(self) -> None:
        if self.playbin is None:
            return
        target = self.target_effective_volume()
        with self._audio_lock:
            if self.playbin is None:
                return
            self.fade_volume(target)

    def set_output_volume(self, value: float) -> None:
        if self.playbin is None:
            return
        value = min(max(value, 0.0), MAX_EFFECTIVE_VOLUME)
        self.playbin.set_property("volume", value)
        self._effective_volume = value

    def target_effective_volume(self) -> float:
        if self.muted or self.soft_paused:
            return SILENCE_VOLUME
        target = (self.volume_percent / 100) * MAX_EFFECTIVE_VOLUME
        if self.spoken_navigation_ducked:
            target *= SPOKEN_NAVIGATION_DUCK_FACTOR
        return target

    def fade_volume(self, target: float) -> None:
        target = min(max(target, 0.0), MAX_EFFECTIVE_VOLUME)
        start = self._effective_volume
        if abs(start - target) < 0.01:
            self.playbin.set_property("volume", target)
            self._effective_volume = target
            return

        delay = VOLUME_FADE_SECONDS / VOLUME_FADE_STEPS
        for step in range(1, VOLUME_FADE_STEPS + 1):
            value = start + (target - start) * (step / VOLUME_FADE_STEPS)
            self.playbin.set_property("volume", value)
            time.sleep(delay)
        self._effective_volume = target


def clamp(value: int, minimum: int, maximum: int) -> int:
    return min(max(value, minimum), maximum)


def smart_resume_rewind_seconds(paused_seconds: float) -> float:
    if paused_seconds < SMART_RESUME_SHORT_PAUSE_SECONDS:
        return 0.0
    if paused_seconds < SMART_RESUME_LONG_PAUSE_SECONDS:
        return SMART_RESUME_MEDIUM_REWIND_SECONDS
    return SMART_RESUME_LONG_REWIND_SECONDS


def load_gstreamer():
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except Exception as error:
        raise PlaybackError(f"GStreamer is unavailable: {error}") from error

    Gst.init(None)
    return Gst
