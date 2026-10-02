from __future__ import annotations

import argparse
import faulthandler
import math
import queue
import signal
import threading
import time
import traceback
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .api import AudiobookshelfClient, AudiobookshelfError, client_from_config
from .appliance_io import AmpShutdownPin, InputEvent, Ky040Pins, NavigationRotaryInput, Sh1122Display, VolumeRotaryInput
from .audio import (
    DEFAULT_MIXER_CONTROLS,
    AudioError,
    VolumeState,
    change_volume,
    play_boot_chime,
    play_control_click,
    toggle_mute,
)
from .bluetooth_audio import (
    BluetoothActionResult,
    BluetoothDevice,
    bluetooth_powered,
    connected_bluetooth_audio_device,
    pair_bluetooth_device,
    preferred_bluetooth_alsa_device,
    scan_bluetooth_devices,
    set_bluetooth_power,
    unpair_connected_bluetooth_audio_device,
)
from .config import (
    DEFAULT_SCREEN_SAVER_DIM_PERCENT,
    LIBRARY_SORT_AUTHOR,
    LIBRARY_SORT_TITLE,
    SCREEN_SAVER_BOOKS,
    SCREEN_SAVER_CHAPTER,
    SCREEN_SAVER_CLOCK,
    AppConfig,
    load_config,
)
from .library_cache import load_cached_books, save_cached_books
from .models import Book
from .network import get_lan_ip
from .player_control import WebPlayerStatus, consume_web_player_commands, save_web_player_status
from .player_state import clear_last_playback, load_player_state, save_last_playback
from .podcast import (
    PodcastError,
    PodcastProgressClient,
    latest_podcast_session,
    podcast_by_book_id,
    podcast_books,
)
from .playback import GStreamerPlayback, PlaybackError
from .rotary_ui import (
    ApplianceMenu,
    CommandType,
    DisplayFrame,
    HomeFrame,
    MenuCommand,
    ScreenSaverFrame,
    SplashFrame,
    SpokenSelection,
    TwoLineFrame,
    VolumeFrame,
    WifiSetupFrame,
    author_sort_text,
    book_is_podcast,
    title_sort_text,
)
from .spoken_navigation import SpokenNavigationFeedback
from .software_update import load_update_state, update_state_is_active
from .wifi import SETUP_HOTSPOT_SSID, SETUP_HOTSPOT_URL, WifiStatus, wifi_status


DEFAULT_REFRESH_SECONDS = 0.14
DEFAULT_STATUS_REFRESH_SECONDS = 2.0
DEFAULT_SPLASH_SECONDS = 0.5
DEFAULT_STARTUP_NETWORK_GRACE_SECONDS = 30.0
DEFAULT_HOME_REFRESH_SECONDS = 60.0
DEFAULT_TITLE_SCROLL_DELAY_SECONDS = 2.0
DEFAULT_TITLE_SCROLL_PX_PER_SECOND = 16.0
DEFAULT_TITLE_SCROLL_LOOP_PAUSE_SECONDS = 2.0
DEFAULT_VOLUME_OVERLAY_SECONDS = 3.0
DEFAULT_IP_OVERLAY_SECONDS = 5.0
DEFAULT_SCREEN_SAVER_IDLE_SECONDS = 300.0
DEFAULT_SCREEN_SAVER_FRAMES_PER_SECOND = 8.0
DEFAULT_UNMUTE_VOLUME_PERCENT = 10
DEFAULT_BOOT_SPLASH_HANDOFF_PATH = "/tmp/audiobookshelf-player-oled-starting"
DEFAULT_BOOT_SPLASH_HANDOFF_SETTLE_SECONDS = 0.3
DEFAULT_PLAYBACK_STATE_SAVE_SECONDS = 5.0
DEFAULT_CONTROL_CLICK_MIN_INTERVAL_SECONDS = 0.045
DEFAULT_SLEEP_CONFIRM_SECONDS = 30
DEFAULT_ACTIVE_BRIGHTNESS_PERCENT = 100
DEFAULT_RUNTIME_CONFIG_REFRESH_SECONDS = 1.0
DEFAULT_SOFTWARE_UPDATE_REFRESH_SECONDS = 0.5
DEFAULT_WAKE_INPUT_QUIET_SECONDS = 0.35
VOLUME_STEP_PERCENT = 5
BOOK_LOADING_FRAME = TwoLineFrame("Grabbing that book", "from the shelf...")
BLUETOOTH_PAIRING_FRAME = TwoLineFrame("Pair Bluetooth", "Put device in pair mode")
BLUETOOTH_POWER_FRAME = TwoLineFrame("Bluetooth", "Updating...")
SOFTWARE_UPDATE_FRAME = TwoLineFrame("UPDATING", "DO NOT POWER OFF")


class PlaybackCommandResult:
    def __init__(
        self,
        session=None,
        client=None,
        error_frame: DisplayFrame | None = None,
    ) -> None:
        self.session = session
        self.client = client
        self.error_frame = error_frame


class BookLoadResult:
    def __init__(
        self,
        books: list[Book] | None = None,
        error_frame: DisplayFrame | None = None,
        generation: int = 0,
    ) -> None:
        self.books = books
        self.error_frame = error_frame
        self.generation = generation


@dataclass(frozen=True)
class BluetoothStatusResult:
    enabled: bool
    connected: bool


@dataclass
class ListeningSleepTimer:
    listened_seconds: float = 0.0
    session_id: str = ""
    prompt_deadline: float = 0.0
    sleeping: bool = False
    sleep_started_at: float = 0.0

    @property
    def prompt_active(self) -> bool:
        return self.prompt_deadline > 0

    def update(
        self,
        now: float,
        elapsed_seconds: float,
        enabled: bool,
        minutes: int,
        session_id: str,
        is_playing: bool,
    ) -> str:
        if not enabled or not session_id:
            was_active = self.prompt_active or self.sleeping
            self.reset(session_id)
            return "cancel" if was_active else ""

        if session_id != self.session_id:
            self.reset(session_id)

        if self.sleeping:
            return ""

        if self.prompt_active:
            if now >= self.prompt_deadline:
                self.prompt_deadline = 0.0
                self.sleeping = True
                self.sleep_started_at = now
                return "sleep"
            return ""

        if is_playing:
            self.listened_seconds += max(0.0, elapsed_seconds)
        if self.listened_seconds < max(1, minutes) * 60:
            return ""

        self.prompt_deadline = now + DEFAULT_SLEEP_CONFIRM_SECONDS
        return "prompt"

    def countdown_seconds(self, now: float) -> int:
        if not self.prompt_active:
            return 0
        return max(0, math.ceil(self.prompt_deadline - now))

    def confirm(self) -> None:
        self.listened_seconds = 0.0
        self.prompt_deadline = 0.0
        self.sleeping = False
        self.sleep_started_at = 0.0

    def wake(self) -> bool:
        if not self.sleeping:
            return False
        self.confirm()
        return True

    def reset(self, session_id: str = "") -> None:
        self.listened_seconds = 0.0
        self.session_id = session_id
        self.prompt_deadline = 0.0
        self.sleeping = False
        self.sleep_started_at = 0.0


def bluetooth_result_frame(result: BluetoothActionResult) -> DisplayFrame:
    if result.success and result.devices:
        return TwoLineFrame("Choose device", "Scroll and click")
    if result.success and result.connected is False:
        return TwoLineFrame("Bluetooth unpaired", "Internal speaker")
    if result.success and result.device_name:
        return TwoLineFrame("Paired Successfully!", result.device_name)
    if result.success:
        return TwoLineFrame("Bluetooth", "On" if result.enabled else "Off")
    return TwoLineFrame("Bluetooth failed", result.message)


def bluetooth_scanning_frame(now: float) -> TwoLineFrame:
    dots = "." * ((int(now * 2) % 3) + 1)
    return TwoLineFrame("Put your device in pairing mode", f"Searching{dots}")


def bluetooth_pairing_frame(frame: TwoLineFrame, now: float) -> TwoLineFrame:
    dots = "." * ((int(now * 2) % 3) + 1)
    return replace(frame, top=f"Pairing{dots}")


class Shutdown:
    requested = False

    def request(self, _signum: int, _frame: object) -> None:
        self.requested = True


class ControlClickFeedback:
    def __init__(self, min_interval_seconds: float = DEFAULT_CONTROL_CLICK_MIN_INTERVAL_SECONDS) -> None:
        self.min_interval_seconds = min_interval_seconds
        self.last_click_at = 0.0

    def click(self, volume_percent: int, muted: bool) -> None:
        if muted or volume_percent <= 0:
            return
        now = time.monotonic()
        if now - self.last_click_at < self.min_interval_seconds:
            return
        self.last_click_at = now
        play_control_click(min(volume_percent, 12))


def enable_stack_dump_signal() -> None:
    try:
        faulthandler.register(signal.SIGUSR1, all_threads=True)
        print("Stack dump enabled on SIGUSR1")
    except Exception as error:
        print(f"Stack dump signal could not be enabled: {error}")


def frame_for_wifi_status(status: WifiStatus, lan_ip: str | None = None) -> DisplayFrame:
    if status.connected and status.ssid == SETUP_HOTSPOT_SSID:
        return setup_frame()

    if status.connected:
        return setup_address_frame(lan_ip)

    return setup_frame()


def splash_frame() -> SplashFrame:
    return SplashFrame("chapter")


def setup_frame() -> WifiSetupFrame:
    return WifiSetupFrame(SETUP_HOTSPOT_SSID, SETUP_HOTSPOT_URL)


def setup_address_frame(lan_ip: str | None = None) -> TwoLineFrame:
    ip = lan_ip or get_lan_ip()
    if ip == "IP unavailable":
        return TwoLineFrame("Wi-Fi connected", "Open setup page")
    return TwoLineFrame("Setup address", f"http://{ip}")


def frame_for_boot_state(
    status: WifiStatus,
    home_frame: DisplayFrame | None = None,
    lan_ip: str | None = None,
    startup_waiting: bool = False,
) -> DisplayFrame:
    if startup_waiting and not status.connected:
        return splash_frame()
    if not status.connected or status.ssid == SETUP_HOTSPOT_SSID:
        return setup_frame()
    return home_frame or setup_address_frame(lan_ip)


def load_home_frame(
    config: AppConfig | None = None,
    client_factory=AudiobookshelfClient,
    lan_ip: str | None = None,
) -> DisplayFrame:
    if config is None:
        config = load_config()
    if not config.is_ready:
        return setup_address_frame(lan_ip)

    try:
        return home_frame_for_books(load_library_books(config, client_factory))
    except AudiobookshelfError:
        return TwoLineFrame("Books unavailable", "Check setup")


def load_library_books(
    config: AppConfig | None = None,
    client_factory=AudiobookshelfClient,
) -> list[Book]:
    config = config or load_config()
    if not config.is_ready:
        return []

    client = client_from_config(config, client_factory)
    library_id = client.choose_library_id(config.library_id)
    return sorted_books_for_menu(
        [*client.get_books(library_id), *podcast_books(config.podcasts)],
        config.library_sort_mode,
    )


def sorted_books_for_menu(
    books: list[Book],
    sort_mode: str = LIBRARY_SORT_TITLE,
) -> list[Book]:
    return sorted(books, key=lambda book: book_menu_sort_key(book, sort_mode))


def book_menu_sort_key(
    book: Book,
    sort_mode: str = LIBRARY_SORT_TITLE,
) -> tuple[str, str, str, str]:
    title = book.display_title
    if sort_mode == LIBRARY_SORT_AUTHOR:
        return (
            author_sort_text(book.author) or "\uffff",
            book.author.casefold(),
            title_sort_text(title),
            title.casefold(),
        )
    return (title_sort_text(title), title.casefold(), book.author.casefold(), "")


def book_load_result(
    config: AppConfig,
    client_factory=AudiobookshelfClient,
    lan_ip: str | None = None,
) -> BookLoadResult:
    if not config.is_ready:
        return BookLoadResult(error_frame=setup_address_frame(lan_ip))

    try:
        return BookLoadResult(books=load_library_books(config, client_factory))
    except AudiobookshelfError as error:
        print(f"Book refresh failed: {error}")
        return BookLoadResult(error_frame=TwoLineFrame("Books unavailable", "Check setup"))


def start_book_load_worker(
    config: AppConfig,
    results: queue.SimpleQueue[BookLoadResult],
    client_factory=AudiobookshelfClient,
    generation: int = 0,
    cache_writer: Callable[[AppConfig, list[Book]], None] | None = None,
) -> None:
    def run() -> None:
        try:
            result = book_load_result(config, client_factory)
            result.generation = generation
            if result.books is not None and cache_writer is not None:
                cache_writer(config, result.books)
            results.put(result)
        except Exception:
            print("Book refresh worker failed:")
            traceback.print_exc()
            results.put(BookLoadResult(error_frame=TwoLineFrame("Books unavailable", "Check setup"), generation=generation))

    threading.Thread(target=run, daemon=True).start()


def bluetooth_status_result() -> BluetoothStatusResult:
    enabled = bluetooth_powered()
    connected = connected_bluetooth_audio_device() is not None if enabled else False
    return BluetoothStatusResult(enabled=enabled, connected=connected)


def start_bluetooth_status_worker(
    results: queue.SimpleQueue[BluetoothStatusResult],
    status_loader: Callable[[], BluetoothStatusResult] = bluetooth_status_result,
) -> None:
    def run() -> None:
        try:
            results.put(status_loader())
        except Exception:
            print("Bluetooth startup status worker failed:")
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()


def home_frame_for_books(books: list[Book]) -> DisplayFrame:
    if not books:
        return TwoLineFrame("No books", "Check library")
    book = books[0]
    return HomeFrame(
        book.display_title,
        book.author,
        series_position=book.series_position,
        is_podcast=book_is_podcast(book),
    )


def scrolled_home_frame(
    frame: DisplayFrame,
    elapsed_seconds: float,
    delay_seconds: float = DEFAULT_TITLE_SCROLL_DELAY_SECONDS,
    pixels_per_second: float = DEFAULT_TITLE_SCROLL_PX_PER_SECOND,
    loop_pause_seconds: float = DEFAULT_TITLE_SCROLL_LOOP_PAUSE_SECONDS,
) -> DisplayFrame:
    if not isinstance(frame, HomeFrame) or elapsed_seconds < delay_seconds:
        return frame
    active_seconds = elapsed_seconds - delay_seconds
    loop_pause_px = round(loop_pause_seconds * pixels_per_second)
    raw_scroll_px = round(active_seconds * pixels_per_second)
    if loop_pause_px and raw_scroll_px % loop_pause_px == 0:
        scroll_px = raw_scroll_px
    else:
        scroll_px = raw_scroll_px
    return HomeFrame(
        title=frame.title,
        author=frame.author,
        series_position=frame.series_position,
        title_scroll_px=scroll_px,
        title_scrolling=True,
        section_letter=frame.section_letter,
        section_letter_fill=frame.section_letter_fill,
        muted=frame.muted,
        bluetooth_connected=frame.bluetooth_connected,
        is_podcast=frame.is_podcast,
    )


def refresh_home_cache(
    cached_home_frame: DisplayFrame | None,
    next_home_frame: DisplayFrame,
    home_frame_loaded_at: float,
    now: float,
) -> tuple[DisplayFrame, float]:
    if same_home_cache_subject(cached_home_frame, next_home_frame):
        return next_home_frame, home_frame_loaded_at
    return next_home_frame, now


def same_home_cache_subject(frame: DisplayFrame | None, next_frame: DisplayFrame) -> bool:
    if isinstance(frame, HomeFrame) and isinstance(next_frame, HomeFrame):
        return (
            frame.title == next_frame.title
            and frame.author == next_frame.author
            and frame.series_position == next_frame.series_position
            and frame.is_podcast == next_frame.is_podcast
        )
    return frame == next_frame


def volume_frame_for_state(state: VolumeState) -> VolumeFrame:
    return VolumeFrame(state.percent, muted=state.muted or state.percent <= 0)


def frame_with_mute_indicator(frame: DisplayFrame, muted: bool) -> DisplayFrame:
    if not muted or isinstance(frame, VolumeFrame):
        return frame
    if hasattr(frame, "muted"):
        return replace(frame, muted=True)
    return frame


def frame_with_status_indicators(
    frame: DisplayFrame,
    muted: bool,
    bluetooth_connected: bool,
) -> DisplayFrame:
    if hasattr(frame, "bluetooth_connected"):
        frame = replace(frame, bluetooth_connected=bluetooth_connected)
    return frame_with_mute_indicator(frame, muted)


def is_bluetooth_pairing_overlay(frame: DisplayFrame | None) -> bool:
    return isinstance(frame, TwoLineFrame) and frame.top.startswith("Pairing")


def screen_saver_is_active(now: float, last_input_at: float, idle_seconds: float) -> bool:
    return idle_seconds > 0 and now - last_input_at >= idle_seconds


def screen_saver_frame(
    now: float,
    last_input_at: float,
    frames_per_second: float = DEFAULT_SCREEN_SAVER_FRAMES_PER_SECOND,
    mode: str = SCREEN_SAVER_CHAPTER,
    words: tuple[str, ...] = ("chapter",),
    brightness_percent: int = DEFAULT_SCREEN_SAVER_DIM_PERCENT,
) -> ScreenSaverFrame:
    elapsed = max(0.0, now - last_input_at)
    if mode == SCREEN_SAVER_CLOCK:
        return ScreenSaverFrame(
            frame_index=int(elapsed * frames_per_second),
            mode=mode,
            words=(),
            clock_text=clock_screen_saver_text(),
            brightness_percent=brightness_percent,
        )
    if mode == SCREEN_SAVER_BOOKS:
        return ScreenSaverFrame(
            frame_index=int(elapsed * frames_per_second),
            mode=mode,
            words=words or ("chapter",),
            brightness_percent=brightness_percent,
        )
    return ScreenSaverFrame(
        frame_index=int(elapsed * frames_per_second),
        mode=SCREEN_SAVER_CHAPTER,
        brightness_percent=brightness_percent,
    )


def clock_screen_saver_text(now: datetime | None = None) -> str:
    current = now or datetime.now()
    return current.strftime("%I:%M %p").lstrip("0")


def screen_saver_words_for_mode(mode: str, books: list[Book]) -> tuple[str, ...]:
    if mode == SCREEN_SAVER_BOOKS:
        titles = tuple(book.display_title for book in books if book.display_title)
        return titles or ("chapter",)
    return ("chapter",)


def update_display_brightness(display, percent: int, current_percent: int) -> int:
    percent = min(max(int(percent), 0), 100)
    if percent == current_percent:
        return current_percent
    try:
        display.set_brightness(percent)
    except Exception as error:
        print(f"OLED brightness update failed: {error}")
    return percent


def input_activity_seen(
    overlay: DisplayFrame | None,
    menu_changed: bool,
    commands: list[MenuCommand],
    pause_playback: bool,
) -> bool:
    return overlay is not None or menu_changed or bool(commands) or pause_playback


def consume_screen_saver_wake_input(
    events: queue.SimpleQueue[InputEvent],
    screen_saver_visible: bool,
    now: float,
    quiet_until: float,
    quiet_seconds: float = DEFAULT_WAKE_INPUT_QUIET_SECONDS,
) -> tuple[bool, float]:
    if not screen_saver_visible and now >= quiet_until:
        return False, quiet_until

    consumed = False
    while True:
        try:
            events.get_nowait()
            consumed = True
        except queue.Empty:
            break

    if consumed:
        quiet_until = now + quiet_seconds
    return screen_saver_visible and consumed, quiet_until


def drain_input_events(events: queue.SimpleQueue[InputEvent]) -> None:
    while True:
        try:
            events.get_nowait()
        except queue.Empty:
            return


def effective_muted(percent: int, muted: bool) -> bool:
    return muted or percent <= 0


def set_amp_shutdown(amp_shutdown, muted: bool, volume_percent: int) -> bool:
    shutdown = effective_muted(volume_percent, muted)
    if amp_shutdown is not None:
        amp_shutdown.set_shutdown(shutdown)
    return shutdown


def restored_audible_volume_state(mixer_controls: tuple[str, ...]) -> VolumeState:
    steps = max(1, DEFAULT_UNMUTE_VOLUME_PERCENT // VOLUME_STEP_PERCENT)
    try:
        state = change_volume(steps, controls=mixer_controls)
    except AudioError:
        return VolumeState(percent=DEFAULT_UNMUTE_VOLUME_PERCENT, muted=False)
    if effective_muted(state.percent, state.muted):
        return VolumeState(percent=DEFAULT_UNMUTE_VOLUME_PERCENT, muted=False)
    return state


def software_volume_state_for_event(
    event: InputEvent,
    fallback_percent: int,
    fallback_muted: bool,
) -> VolumeState:
    if event.name == "volume":
        return VolumeState(
            percent=min(max(fallback_percent + event.steps * VOLUME_STEP_PERCENT, 0), 100),
            muted=False,
        )

    if event.name == "volume_click":
        if effective_muted(fallback_percent, fallback_muted):
            return VolumeState(
                percent=fallback_percent if fallback_percent > 0 else DEFAULT_UNMUTE_VOLUME_PERCENT,
                muted=False,
            )
        return VolumeState(percent=fallback_percent, muted=True)

    return VolumeState(percent=fallback_percent, muted=fallback_muted)


def unmute_for_audible_playback_commands(
    commands: list[MenuCommand],
    fallback_percent: int,
    fallback_muted: bool,
    mixer_controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    software_volume_only: bool = False,
) -> tuple[list[MenuCommand], int, bool, bool, bool]:
    if not effective_muted(fallback_percent, fallback_muted):
        return commands, fallback_percent, fallback_muted, False, False

    audible_command_types = {CommandType.PLAY_BOOK, CommandType.TOGGLE_PLAYBACK}
    if not any(command.type in audible_command_types for command in commands):
        return commands, fallback_percent, fallback_muted, False, False

    if software_volume_only:
        state = VolumeState(
            percent=fallback_percent if fallback_percent > 0 else DEFAULT_UNMUTE_VOLUME_PERCENT,
            muted=False,
        )
    else:
        state = restored_audible_volume_state(mixer_controls)

    resume_from_muted_play = any(command.type == CommandType.TOGGLE_PLAYBACK for command in commands)
    filtered_commands = [command for command in commands if command.type != CommandType.TOGGLE_PLAYBACK]
    return filtered_commands, state.percent, state.muted, True, resume_from_muted_play


def run_playback_action(action, label: str) -> None:
    def run() -> None:
        try:
            action()
        except Exception:
            print(f"Playback {label} failed:")
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()


def save_playback_state(playback: GStreamerPlayback) -> bool:
    if playback.session is None:
        return False
    save_last_playback(
        playback.session.library_item_id,
        playback.session.title,
        playback.current_time,
    )
    return True


def poll_playback_safely(playback: GStreamerPlayback) -> DisplayFrame | None:
    try:
        playback.poll()
    except PlaybackError as error:
        print(f"Playback poll failed: {error}")
        return TwoLineFrame("Playback stopped", "Check audio")
    return None


def web_status_for_playback(
    playback: GStreamerPlayback,
    volume_percent: int,
    muted: bool,
) -> WebPlayerStatus:
    if playback.session is None:
        return WebPlayerStatus(volume_percent=volume_percent, muted=muted or volume_percent <= 0)
    return WebPlayerStatus(
        title=playback.session.title,
        author=playback.session.author,
        current_time=playback.current_time,
        duration=playback.session.duration,
        is_playing=playback.is_playing,
        volume_percent=volume_percent,
        muted=muted or volume_percent <= 0,
    )


def publish_web_player_status(
    playback: GStreamerPlayback,
    volume_percent: int,
    muted: bool,
) -> None:
    save_web_player_status(web_status_for_playback(playback, volume_percent, muted))


def pause_and_publish_playback(
    playback: GStreamerPlayback,
    menu: ApplianceMenu,
    volume_percent: int,
    muted: bool,
) -> None:
    if playback.is_playing:
        playback.pause(sync=True)
    playback.is_playing = False
    menu.update_playback(playback.current_time, False)
    publish_web_player_status(playback, volume_percent, muted)


def handle_web_player_commands(
    playback: GStreamerPlayback,
    menu: ApplianceMenu,
    volume_percent: int,
    muted: bool,
) -> tuple[int, bool, bool, bool]:
    changed = False
    refresh_library = False
    for command in consume_web_player_commands():
        if command.action == "refresh_library":
            if playback.is_playing:
                playback.pause(sync=True)
            playback.stop()
            clear_last_playback()
            menu.set_books([])
            menu.reset_to_library()
            changed = True
            refresh_library = True
            continue

        if command.action == "resort_library":
            selected_book_id = menu.books[menu.book_index].id if menu.books else ""
            sort_mode = load_config().library_sort_mode
            menu.set_library_sort_mode(sort_mode)
            menu.set_books(sorted_books_for_menu(menu.books, sort_mode))
            if selected_book_id:
                menu.book_index = next(
                    (index for index, book in enumerate(menu.books) if book.id == selected_book_id),
                    menu.book_index,
                )
            changed = True
            continue

        if command.action == "pause":
            if playback.is_playing:
                playback.pause(sync=True)
                menu.update_playback(playback.current_time, playback.is_playing)
                changed = True
            continue

        if command.action == "play":
            if playback.session is not None and not playback.is_playing:
                if volume_percent <= 0:
                    volume_percent = DEFAULT_UNMUTE_VOLUME_PERCENT
                muted = False
                playback.resume(sync=False, percent=volume_percent, muted=muted)
                menu.update_playback(playback.current_time, playback.is_playing)
                changed = True
            continue

        if command.action == "volume" and command.value is not None:
            was_effectively_muted = effective_muted(volume_percent, muted)
            volume_percent = min(max(command.value, 0), 100)
            muted = volume_percent <= 0
            playback.set_volume_state(volume_percent, muted)
            if volume_percent <= 0 and playback.is_playing:
                playback.pause(sync=False)
                menu.update_playback(playback.current_time, playback.is_playing)
            elif was_effectively_muted and volume_percent > 0:
                muted = False
                playback.set_volume_state(volume_percent, muted)
            changed = True
    return volume_percent, muted, changed, refresh_library


def run_oled_service(
    display: Sh1122Display,
    refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
    status_refresh_seconds: float = DEFAULT_STATUS_REFRESH_SECONDS,
    splash_seconds: float = DEFAULT_SPLASH_SECONDS,
    startup_network_grace_seconds: float = DEFAULT_STARTUP_NETWORK_GRACE_SECONDS,
    home_refresh_seconds: float = DEFAULT_HOME_REFRESH_SECONDS,
    nav_input_enabled: bool = True,
    nav_pins: Ky040Pins = Ky040Pins(clk=5, dt=6, sw=13, reversed=True),
    volume_input_enabled: bool = True,
    volume_pins: Ky040Pins = Ky040Pins(clk=12, dt=16, sw=26, reversed=True),
    mixer_controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    screen_saver_idle_seconds: float = DEFAULT_SCREEN_SAVER_IDLE_SECONDS,
    screen_saver_frames_per_second: float = DEFAULT_SCREEN_SAVER_FRAMES_PER_SECOND,
    amp_shutdown_pin: int | None = None,
    software_volume_only: bool = True,
) -> None:
    enable_stack_dump_signal()
    shutdown = Shutdown()
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)
    playback = GStreamerPlayback()
    spoken_navigation = SpokenNavigationFeedback(playback.set_spoken_navigation_ducked)
    amp_shutdown: AmpShutdownPin | None = None
    service_started_at = time.monotonic()

    try:
        display.show(splash_frame())
        sleep_until_shutdown(shutdown, splash_seconds)

        events: queue.SimpleQueue[InputEvent] = queue.SimpleQueue()
        nav_input: NavigationRotaryInput | None = None
        if nav_input_enabled:
            try:
                nav_input = NavigationRotaryInput(events, nav=nav_pins)
                print(
                    "Navigation rotary enabled on "
                    f"CLK GPIO{nav_pins.clk}, DT GPIO{nav_pins.dt}, SW GPIO{nav_pins.sw}, "
                    f"reversed={nav_pins.reversed}"
                )
            except Exception as error:
                print(f"Navigation rotary could not start: {error}")

        volume_input: VolumeRotaryInput | None = None
        if volume_input_enabled:
            try:
                volume_input = VolumeRotaryInput(events, volume=volume_pins)
                print(
                    "Volume rotary enabled on "
                    f"CLK GPIO{volume_pins.clk}, DT GPIO{volume_pins.dt}, SW GPIO{volume_pins.sw}"
                )
            except Exception as error:
                print(f"Volume rotary could not start: {error}")

        software_volume = 50
        software_muted = False
        control_click_feedback = ControlClickFeedback()
        if software_volume_only:
            print("Software-only volume control enabled")
        if amp_shutdown_pin is not None:
            try:
                amp_shutdown = AmpShutdownPin(amp_shutdown_pin)
                set_amp_shutdown(amp_shutdown, muted=False, volume_percent=software_volume)
                print(f"MAX98357 amp shutdown enabled on GPIO{amp_shutdown_pin}")
            except Exception as error:
                amp_shutdown = None
                print(f"MAX98357 amp shutdown could not start: {error}")

        startup_config = load_config()
        runtime_config = startup_config
        menu = ApplianceMenu(
            sorted_books_for_menu(load_cached_books(startup_config), startup_config.library_sort_mode),
            library_sort_mode=startup_config.library_sort_mode,
        )
        menu.set_bluetooth_enabled(False)
        menu.set_bluetooth_connected(False)
        menu.set_startup_resume(load_player_state())
        books_error_frame: DisplayFrame | None = None
        cached_home_frame: DisplayFrame | None = None
        cached_status: WifiStatus | None = None
        home_frame_loaded_at = 0.0
        last_home_load = 0.0
        book_refresh_started = False
        book_load_in_progress = False
        book_load_generation = 0
        last_status_load = 0.0
        overlay_frame: DisplayFrame | None = None
        overlay_until = 0.0
        playback_loading = False
        bluetooth_enabled = False
        bluetooth_connected = False
        bluetooth_pairing_in_progress = False
        playback_results: queue.SimpleQueue[PlaybackCommandResult] = queue.SimpleQueue()
        book_load_results: queue.SimpleQueue[BookLoadResult] = queue.SimpleQueue()
        bluetooth_results: queue.SimpleQueue[BluetoothActionResult] = queue.SimpleQueue()
        bluetooth_status_results: queue.SimpleQueue[BluetoothStatusResult] = queue.SimpleQueue()
        start_bluetooth_status_worker(bluetooth_status_results)
        last_input_at = time.monotonic()
        last_loop_at = last_input_at
        last_runtime_config_load = last_input_at
        last_software_update_load = 0.0
        software_update_active = False
        software_update_screen_visible = False
        sleep_timer = ListeningSleepTimer()
        display_brightness_percent = DEFAULT_ACTIVE_BRIGHTNESS_PERCENT
        screen_saver_visible = False
        wake_input_quiet_until = 0.0
        paused_for_mute = False
        last_playback_volume_state: tuple[int, bool] | None = None
        last_playback_state_save = 0.0
        boot_chime_played = False
        while not shutdown.requested:
            try:
                now = time.monotonic()
                full_loop_elapsed = max(0.0, now - last_loop_at)
                loop_elapsed = min(full_loop_elapsed, 1.0)
                last_loop_at = now
                if now - last_software_update_load >= DEFAULT_SOFTWARE_UPDATE_REFRESH_SECONDS:
                    software_update_active = update_state_is_active(load_update_state())
                    last_software_update_load = now
                if software_update_active:
                    drain_input_events(events)
                    spoken_navigation.cancel()
                    screen_saver_visible = False
                    display_brightness_percent = update_display_brightness(
                        display,
                        DEFAULT_ACTIVE_BRIGHTNESS_PERCENT,
                        display_brightness_percent,
                    )
                    display.show(SOFTWARE_UPDATE_FRAME)
                    if not software_update_screen_visible:
                        software_update_screen_visible = True
                        pause_and_publish_playback(
                            playback,
                            menu,
                            software_volume,
                            software_muted,
                        )
                    sleep_until_shutdown(shutdown, refresh_seconds)
                    continue
                software_update_screen_visible = False
                if now - last_runtime_config_load >= DEFAULT_RUNTIME_CONFIG_REFRESH_SECONDS:
                    runtime_config = load_config()
                    last_runtime_config_load = now
                woke_screen_saver, wake_input_quiet_until = consume_screen_saver_wake_input(
                    events,
                    screen_saver_visible,
                    now,
                    wake_input_quiet_until,
                )
                suppress_wake_input = woke_screen_saver or now < wake_input_quiet_until
                if woke_screen_saver:
                    screen_saver_visible = False
                    last_input_at = now
                    if sleep_timer.wake():
                        menu.dismiss_sleep_confirmation()
                    display_brightness_percent = update_display_brightness(
                        display,
                        DEFAULT_ACTIVE_BRIGHTNESS_PERCENT,
                        display_brightness_percent,
                    )
                if suppress_wake_input:
                    overlay = None
                    menu_changed = False
                    commands = []
                    pause_playback = False
                    resume_playback = False
                else:
                    (
                        overlay,
                        software_volume,
                        software_muted,
                        menu_changed,
                        commands,
                        pause_playback,
                        resume_playback,
                    ) = handle_oled_input_events(
                        events,
                        menu,
                        mixer_controls=mixer_controls,
                        fallback_percent=software_volume,
                        fallback_muted=software_muted,
                        software_volume_only=software_volume_only,
                        bluetooth_enabled=bluetooth_enabled,
                        bluetooth_connected=bluetooth_connected,
                        control_click_feedback=(
                            lambda: control_click_feedback.click(software_volume, software_muted)
                            if load_config().control_click_enabled
                            else None
                        ),
                        spoken_navigation_feedback=(
                            lambda selection: spoken_navigation.request(
                                selection.text,
                                delay_seconds=selection.delay_seconds,
                                volume_percent=software_volume,
                                muted=software_muted,
                            )
                            if runtime_config.spoken_navigation_enabled
                            else None
                        ),
                        spoken_navigation_cancel=(
                            spoken_navigation.cancel
                            if runtime_config.spoken_navigation_enabled
                            else None
                        ),
                    )
                commands, software_volume, software_muted, unmuted_for_play, resume_from_muted_play = (
                    unmute_for_audible_playback_commands(
                        commands,
                        software_volume,
                        software_muted,
                        mixer_controls=mixer_controls,
                        software_volume_only=software_volume_only,
                    )
                )
                if unmuted_for_play:
                    resume_playback = resume_playback or resume_from_muted_play
                    menu_changed = True
                while True:
                    try:
                        playback_result = playback_results.get_nowait()
                    except queue.Empty:
                        break
                    playback_loading = False
                    menu_changed = True
                    cached_home_frame = None
                    home_frame_loaded_at = now
                    if playback_result.error_frame is not None:
                        overlay = playback_result.error_frame
                    elif playback_result.session is not None:
                        menu.set_session(playback_result.session, is_playing=playback.is_playing)
                        if save_playback_state(playback):
                            last_playback_state_save = now
                while True:
                    try:
                        book_result = book_load_results.get_nowait()
                    except queue.Empty:
                        break
                    if book_result.generation != book_load_generation:
                        continue
                    book_load_in_progress = False
                    cached_home_frame = None
                    home_frame_loaded_at = now
                    if book_result.books is not None:
                        menu.set_books(book_result.books)
                        books_error_frame = (
                            None
                            if book_result.books
                            else TwoLineFrame("No books", "Check library")
                        )
                    elif book_result.error_frame is not None and not menu.books:
                        books_error_frame = book_result.error_frame
                while True:
                    try:
                        bluetooth_status = bluetooth_status_results.get_nowait()
                    except queue.Empty:
                        break
                    bluetooth_enabled = bluetooth_status.enabled
                    bluetooth_connected = bluetooth_status.connected
                    menu.set_bluetooth_enabled(bluetooth_enabled)
                    menu.set_bluetooth_connected(bluetooth_connected)
                    playback.set_bluetooth_output_enabled(bluetooth_connected)
                    if bluetooth_connected:
                        run_playback_action(playback.refresh_audio_output, "Bluetooth startup audio output refresh")
                    menu_changed = True
                while True:
                    try:
                        bluetooth_result = bluetooth_results.get_nowait()
                    except queue.Empty:
                        break
                    bluetooth_enabled = bluetooth_result.enabled if bluetooth_result.enabled is not None else bluetooth_enabled
                    if bluetooth_result.connected is not None:
                        bluetooth_connected = bluetooth_result.connected
                    elif bluetooth_result.enabled is False:
                        bluetooth_connected = False
                    menu.set_bluetooth_enabled(bluetooth_enabled)
                    menu.set_bluetooth_connected(bluetooth_connected)
                    playback.set_bluetooth_output_enabled(bluetooth_connected)
                    menu_changed = True
                    bluetooth_pairing_in_progress = False
                    if bluetooth_result.devices:
                        menu.set_bluetooth_devices(
                            [(device.address, device.name) for device in bluetooth_result.devices]
                        )
                        overlay = None
                    else:
                        if (
                            bluetooth_result.success
                            and bluetooth_result.device_name
                            and bluetooth_result.connected is not False
                        ):
                            bluetooth_connected = True
                            menu.set_bluetooth_connected(True)
                            menu.close_bluetooth_menu()
                        overlay = bluetooth_result_frame(bluetooth_result)
                    if bluetooth_result.success:
                        run_playback_action(playback.refresh_audio_output, "Bluetooth audio output refresh")
                playback_volume_state = (software_volume, software_muted)
                if playback_volume_state != last_playback_volume_state and not resume_playback:
                    if unmuted_for_play:
                        playback.set_volume_state(software_volume, software_muted)
                    else:
                        run_playback_action(
                            lambda percent=software_volume, muted=software_muted: playback.set_volume_state(
                                percent, muted
                            ),
                            "volume update",
                        )
                    last_playback_volume_state = playback_volume_state
                try:
                    set_amp_shutdown(amp_shutdown, software_muted, software_volume)
                except Exception as error:
                    amp_shutdown = None
                    print(f"MAX98357 amp shutdown control failed: {error}")
                input_activity = input_activity_seen(
                    overlay,
                    menu_changed,
                    commands,
                    pause_playback or resume_playback,
                )
                if input_activity:
                    last_input_at = now
                    menu.note_input_activity()
                    if sleep_timer.wake():
                        menu.dismiss_sleep_confirmation()
                        menu_changed = True
                    display_brightness_percent = update_display_brightness(
                        display,
                        DEFAULT_ACTIVE_BRIGHTNESS_PERCENT,
                        display_brightness_percent,
                    )
                menu.tick_section_letter(loop_elapsed)
                if pause_playback and not resume_playback:
                    paused_for_mute = paused_for_mute or playback.is_playing
                    playback.is_playing = False
                    run_playback_action(lambda: playback.pause(sync=False), "mute pause")
                    menu.update_playback(playback.current_time, playback.is_playing)
                    publish_web_player_status(playback, software_volume, software_muted)
                    menu_changed = True
                elif resume_playback:
                    if paused_for_mute and not playback.is_playing:
                        run_playback_action(
                            lambda percent=software_volume, muted=software_muted: playback.resume(
                                sync=False,
                                percent=percent,
                                muted=muted,
                            ),
                            "mute resume",
                        )
                        last_playback_volume_state = playback_volume_state
                        menu.update_playback(playback.current_time, True)
                        publish_web_player_status(playback, software_volume, software_muted)
                        menu_changed = True
                    elif unmuted_for_play:
                        playback.set_volume_state(software_volume, software_muted)
                        last_playback_volume_state = playback_volume_state
                    paused_for_mute = False
                elif unmuted_for_play:
                    paused_for_mute = False
                if menu_changed:
                    overlay_frame = None
                    cached_home_frame = None
                    home_frame_loaded_at = now
                for command in commands:
                    if command.type == CommandType.CONFIRM_STILL_LISTENING:
                        sleep_timer.confirm()
                    command_overlay = handle_menu_command(command, menu, playback, playback_results, bluetooth_results)
                    if command.type in (
                        CommandType.PAUSE_PLAYBACK,
                        CommandType.TOGGLE_PLAYBACK,
                        CommandType.SEEK_CHAPTER,
                        CommandType.HOME,
                        CommandType.CONFIRM_STILL_LISTENING,
                    ):
                        publish_web_player_status(playback, software_volume, software_muted)
                    menu_changed = True
                    cached_home_frame = None
                    home_frame_loaded_at = now
                    if command.type == CommandType.PAIR_BLUETOOTH_DEVICE:
                        bluetooth_pairing_in_progress = True
                    if command_overlay is not None:
                        overlay = command_overlay
                    if command_overlay == BOOK_LOADING_FRAME:
                        playback_loading = True
                web_volume, web_muted, web_changed, web_refresh_library = handle_web_player_commands(
                    playback,
                    menu,
                    software_volume,
                    software_muted,
                )
                if web_changed:
                    software_volume = web_volume
                    software_muted = web_muted
                    last_playback_volume_state = (software_volume, software_muted)
                    menu_changed = True
                    cached_home_frame = None
                    home_frame_loaded_at = now
                    if playback.is_playing and (sleep_timer.prompt_active or sleep_timer.sleeping):
                        sleep_timer.confirm()
                        menu.dismiss_sleep_confirmation()
                        last_input_at = now
                        display_brightness_percent = update_display_brightness(
                            display,
                            DEFAULT_ACTIVE_BRIGHTNESS_PERCENT,
                            display_brightness_percent,
                        )
                if web_refresh_library:
                    book_load_generation += 1
                    book_refresh_started = False
                    book_load_in_progress = False
                    books_error_frame = None
                    last_home_load = 0.0
                    playback_loading = False
                if runtime_config.spoken_navigation_enabled:
                    speech_output_device = playback.audio_output_device
                    if (
                        bluetooth_connected
                        and not speech_output_device
                        and spoken_navigation.ready_to_start
                    ):
                        speech_output_device = preferred_bluetooth_alsa_device()
                    spoken_navigation.poll(speech_output_device)
                else:
                    spoken_navigation.cancel()
                if overlay is not None:
                    overlay_frame = overlay
                    overlay_seconds = (
                        60.0
                        if overlay in (BOOK_LOADING_FRAME, BLUETOOTH_PAIRING_FRAME)
                        or is_bluetooth_pairing_overlay(overlay)
                        else DEFAULT_IP_OVERLAY_SECONDS
                        if isinstance(overlay, TwoLineFrame)
                        else DEFAULT_VOLUME_OVERLAY_SECONDS
                    )
                    overlay_until = now + overlay_seconds
                if playback_loading and overlay_frame is None:
                    overlay_frame = BOOK_LOADING_FRAME
                    overlay_until = now + 60.0

                session_id = ""
                if playback.session is not None:
                    session_id = playback.session.id or playback.session.library_item_id
                sleep_event = sleep_timer.update(
                    now=now,
                    elapsed_seconds=full_loop_elapsed,
                    enabled=runtime_config.sleep_timer_enabled,
                    minutes=runtime_config.sleep_timer_minutes,
                    session_id=session_id,
                    is_playing=playback.is_playing,
                )
                if sleep_event == "prompt":
                    pause_and_publish_playback(
                        playback,
                        menu,
                        software_volume,
                        software_muted,
                    )
                    menu.show_sleep_confirmation(sleep_timer.countdown_seconds(now))
                    overlay_frame = None
                    overlay_until = 0.0
                    last_input_at = now
                    menu_changed = True
                elif sleep_event == "sleep":
                    pause_and_publish_playback(
                        playback,
                        menu,
                        software_volume,
                        software_muted,
                    )
                    menu.dismiss_sleep_confirmation()
                    menu_changed = True
                elif sleep_event == "cancel":
                    menu.dismiss_sleep_confirmation()
                    if playback.session is not None and not playback.is_playing:
                        playback.resume(sync=False)
                        menu.update_playback(playback.current_time, playback.is_playing)
                    menu_changed = True
                if sleep_timer.prompt_active:
                    menu.update_sleep_confirmation(sleep_timer.countdown_seconds(now))

                if cached_status is None or now - last_status_load >= status_refresh_seconds:
                    cached_status = wifi_status()
                    last_status_load = now
                status = cached_status
                startup_waiting = now - service_started_at < startup_network_grace_seconds

                if overlay_frame is not None and now < overlay_until:
                    if bluetooth_pairing_in_progress and is_bluetooth_pairing_overlay(overlay_frame):
                        overlay_until = now + 60.0
                    visible_overlay = (
                        bluetooth_scanning_frame(now)
                        if overlay_frame == BLUETOOTH_PAIRING_FRAME
                        else bluetooth_pairing_frame(overlay_frame, now)
                        if bluetooth_pairing_in_progress and is_bluetooth_pairing_overlay(overlay_frame)
                        else overlay_frame
                    )
                    display_brightness_percent = update_display_brightness(
                        display,
                        DEFAULT_ACTIVE_BRIGHTNESS_PERCENT,
                        display_brightness_percent,
                    )
                    screen_saver_visible = False
                    display.show(
                        frame_with_status_indicators(
                            visible_overlay,
                            software_muted or software_volume <= 0,
                            bluetooth_connected,
                        )
                    )
                    sleep_until_shutdown(shutdown, refresh_seconds)
                    continue
                overlay_frame = None

                if status.connected and status.ssid != SETUP_HOTSPOT_SSID:
                    if playback.session is not None and not playback_loading:
                        playback_error_frame = poll_playback_safely(playback)
                        if playback_error_frame is not None:
                            overlay_frame = playback_error_frame
                            overlay_until = now + DEFAULT_IP_OVERLAY_SECONDS
                            menu_changed = True
                            cached_home_frame = None
                            home_frame_loaded_at = now
                            display_brightness_percent = update_display_brightness(
                                display,
                                DEFAULT_ACTIVE_BRIGHTNESS_PERCENT,
                                display_brightness_percent,
                            )
                            screen_saver_visible = False
                            display.show(
                                frame_with_status_indicators(
                                    overlay_frame,
                                    software_muted or software_volume <= 0,
                                    bluetooth_connected,
                                )
                            )
                            sleep_until_shutdown(shutdown, refresh_seconds)
                            continue
                        menu.update_playback(playback.current_time, playback.is_playing)
                        if now - last_playback_state_save >= DEFAULT_PLAYBACK_STATE_SAVE_SECONDS:
                            if save_playback_state(playback):
                                last_playback_state_save = now
                        menu.update_title_scroll(
                            loop_elapsed,
                            delay_seconds=DEFAULT_TITLE_SCROLL_DELAY_SECONDS,
                            pixels_per_second=DEFAULT_TITLE_SCROLL_PX_PER_SECOND,
                        )
                        if menu.tick_chapter_confirm_timeout(loop_elapsed):
                            cached_home_frame = None
                            home_frame_loaded_at = now
                        if menu.tick_home_return_timeout(loop_elapsed):
                            cached_home_frame = None
                            home_frame_loaded_at = now
                    if (
                        not book_load_in_progress
                        and (not book_refresh_started or now - last_home_load >= home_refresh_seconds)
                    ):
                        last_home_load = now
                        book_refresh_started = True
                        config = load_config()
                        if not config.is_ready:
                            books_error_frame = setup_address_frame()
                        else:
                            book_load_in_progress = True
                            menu.set_library_sort_mode(config.library_sort_mode)
                            start_book_load_worker(
                                config,
                                book_load_results,
                                generation=book_load_generation,
                                cache_writer=save_cached_books,
                            )

                    next_home_frame = books_error_frame if books_error_frame and not menu.books else menu.render()
                    cached_home_frame, home_frame_loaded_at = refresh_home_cache(
                        cached_home_frame,
                        next_home_frame,
                        home_frame_loaded_at,
                        now,
                    )
                    home_frame = scrolled_home_frame(cached_home_frame, now - home_frame_loaded_at)
                    frame = frame_for_boot_state(status, home_frame, startup_waiting=startup_waiting)
                else:
                    books_error_frame = None
                    book_refresh_started = False
                    cached_home_frame = None
                    frame = frame_for_boot_state(status, startup_waiting=startup_waiting)
                if not boot_chime_played and not isinstance(frame, SplashFrame):
                    boot_chime_played = True
                    play_boot_chime()
                normal_screen_saver_active = screen_saver_is_active(
                    now,
                    last_input_at,
                    screen_saver_idle_seconds,
                ) and not sleep_timer.prompt_active
                screen_saver_active = sleep_timer.sleeping or normal_screen_saver_active
                if screen_saver_active:
                    screen_saver_mode = runtime_config.screen_saver_mode
                    screen_saver_started_at = (
                        sleep_timer.sleep_started_at
                        if sleep_timer.sleeping
                        else last_input_at
                    )
                    frame = screen_saver_frame(
                        now,
                        screen_saver_started_at,
                        screen_saver_frames_per_second,
                        mode=screen_saver_mode,
                        words=screen_saver_words_for_mode(screen_saver_mode, menu.books),
                        brightness_percent=runtime_config.screen_saver_dim_percent,
                    )
                display_brightness_percent = update_display_brightness(
                    display,
                    DEFAULT_ACTIVE_BRIGHTNESS_PERCENT,
                    display_brightness_percent,
                )
                screen_saver_visible = screen_saver_active
                publish_web_player_status(playback, software_volume, software_muted)
                display.show(
                    frame_with_status_indicators(
                        frame,
                        software_muted or software_volume <= 0,
                        bluetooth_connected,
                    )
                )
                sleep_until_shutdown(shutdown, refresh_seconds)
            except Exception:
                print("OLED service loop error:")
                traceback.print_exc()
                try:
                    screen_saver_visible = False
                    display.show(TwoLineFrame("OLED error", "See log"))
                except Exception:
                    print("OLED error frame could not be displayed:")
                traceback.print_exc()
                sleep_until_shutdown(shutdown, 5.0)
    finally:
        spoken_navigation.close()
        if amp_shutdown is not None:
            amp_shutdown.close()
        playback.stop()
        display.close()


def handle_input_events(
    events: queue.SimpleQueue[InputEvent],
    mixer_controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
) -> tuple[DisplayFrame | None, int, bool]:
    return handle_input_events_with_fallback(events, mixer_controls=mixer_controls)


def handle_oled_input_events(
    events: queue.SimpleQueue[InputEvent],
    menu: ApplianceMenu,
    mixer_controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    fallback_percent: int = 50,
    fallback_muted: bool = False,
    software_volume_only: bool = False,
    bluetooth_enabled: bool = True,
    bluetooth_connected: bool = False,
    control_click_feedback: Callable[[], None] | None = None,
    spoken_navigation_feedback: Callable[[SpokenSelection], None] | None = None,
    spoken_navigation_cancel: Callable[[], None] | None = None,
) -> tuple[DisplayFrame | None, int, bool, bool, list[MenuCommand], bool, bool]:
    frame: DisplayFrame | None = None
    menu_changed = False
    commands = []
    pause_playback = False
    resume_playback = False
    while True:
        try:
            event = events.get_nowait()
        except queue.Empty:
            return frame, fallback_percent, fallback_muted, menu_changed, commands, pause_playback, resume_playback

        if event.name == "nav":
            if event.steps and control_click_feedback is not None:
                control_click_feedback()
            previous_selection = menu.spoken_selection()
            menu.rotate_nav(event.steps)
            speak_changed_selection(menu, previous_selection, spoken_navigation_feedback)
            menu_changed = True
            continue

        if event.name == "nav_click":
            if control_click_feedback is not None:
                control_click_feedback()
            print("Navigation click received")
            if spoken_navigation_cancel is not None:
                spoken_navigation_cancel()
            previous_selection = menu.spoken_selection()
            commands.extend(menu.click_nav())
            speak_changed_selection(menu, previous_selection, spoken_navigation_feedback)
            menu_changed = True
            continue

        if event.name == "nav_hold":
            print("Navigation hold received")
            if spoken_navigation_cancel is not None:
                spoken_navigation_cancel()
            previous_selection = menu.spoken_selection()
            commands.extend(
                menu.hold_nav(
                    bluetooth_enabled=bluetooth_enabled,
                    bluetooth_connected=bluetooth_connected,
                )
            )
            speak_changed_selection(menu, previous_selection, spoken_navigation_feedback)
            menu_changed = True
            continue

        was_effectively_muted = effective_muted(fallback_percent, fallback_muted)
        if software_volume_only and event.name in {"volume", "volume_click"}:
            state = software_volume_state_for_event(event, fallback_percent, fallback_muted)
            fallback_percent = state.percent
            fallback_muted = state.muted
            frame = volume_frame_for_state(state)
            pause_playback = pause_playback or (not was_effectively_muted and frame.is_muted)
            resume_playback = resume_playback or (was_effectively_muted and not frame.is_muted)
            continue

        try:
            if event.name == "volume":
                state = change_volume(event.steps, controls=mixer_controls)
                fallback_percent = state.percent
                fallback_muted = state.muted
                frame = volume_frame_for_state(state)
                pause_playback = pause_playback or (not was_effectively_muted and frame.is_muted)
                resume_playback = resume_playback or (was_effectively_muted and not frame.is_muted)
            elif event.name == "volume_click":
                state = toggle_mute(controls=mixer_controls)
                if was_effectively_muted and effective_muted(state.percent, state.muted):
                    state = restored_audible_volume_state(mixer_controls)
                fallback_percent = state.percent
                fallback_muted = state.muted
                frame = volume_frame_for_state(state)
                pause_playback = pause_playback or (not was_effectively_muted and frame.is_muted)
                resume_playback = resume_playback or (was_effectively_muted and not frame.is_muted)
            elif event.name == "show_ip":
                frame = setup_address_frame()
        except AudioError as error:
            print(f"Volume control failed: {error}")
            if event.name == "volume":
                fallback_percent = min(max(fallback_percent + event.steps * 5, 0), 100)
                fallback_muted = False
                frame = VolumeFrame(fallback_percent, muted=fallback_percent <= 0)
                pause_playback = pause_playback or (not was_effectively_muted and frame.is_muted)
                resume_playback = resume_playback or (was_effectively_muted and not frame.is_muted)
            elif event.name == "volume_click":
                if was_effectively_muted and fallback_percent <= 0:
                    fallback_percent = DEFAULT_UNMUTE_VOLUME_PERCENT
                    fallback_muted = False
                else:
                    fallback_muted = not fallback_muted
                frame = VolumeFrame(fallback_percent, muted=fallback_muted or fallback_percent <= 0)
                pause_playback = pause_playback or (not was_effectively_muted and frame.is_muted)
                resume_playback = resume_playback or (was_effectively_muted and not frame.is_muted)
            elif event.name == "show_ip":
                frame = setup_address_frame()


def speak_changed_selection(
    menu: ApplianceMenu,
    previous_selection: SpokenSelection | None,
    feedback: Callable[[SpokenSelection], None] | None,
) -> None:
    if feedback is None:
        return
    selection = menu.spoken_selection()
    if selection is not None and selection != previous_selection:
        feedback(selection)


def handle_menu_command(
    command: MenuCommand,
    menu: ApplianceMenu,
    playback: GStreamerPlayback,
    playback_results: queue.SimpleQueue[PlaybackCommandResult] | None = None,
    bluetooth_results: queue.SimpleQueue[BluetoothActionResult] | None = None,
) -> DisplayFrame | None:
    if command.type == CommandType.PLAY_BOOK:
        if should_return_to_active_session(command, playback):
            menu.set_session(playback.session, is_playing=playback.is_playing)
            menu.update_playback(playback.current_time, playback.is_playing)
            return None

        if playback_results is not None:
            start_play_book_worker(command, playback, playback_results)
            return BOOK_LOADING_FRAME

        try:
            result = play_book_command_result(command, playback)
            if result.error_frame is not None:
                return result.error_frame
            session = result.session
            if session is None:
                return TwoLineFrame("Could not play", "Check setup")
            menu.set_session(session, is_playing=True)
            return None
        except (AudiobookshelfError, PlaybackError) as error:
            print(f"Playback failed: {error}")
            return TwoLineFrame("Could not play", "Check setup")

    if command.type == CommandType.PAUSE_PLAYBACK:
        if playback.is_playing:
            playback.pause(sync=True)
            menu.update_playback(playback.current_time, playback.is_playing)
        return None

    if command.type == CommandType.TOGGLE_PLAYBACK:
        playback.toggle()
        menu.update_playback(playback.current_time, playback.is_playing)
        return None

    if command.type == CommandType.SEEK_CHAPTER:
        playback.seek_global(command.seek_time)
        if not playback.is_playing:
            playback.resume(sync=False)
        menu.update_playback(playback.current_time, playback.is_playing)
        return None

    if command.type == CommandType.CONFIRM_STILL_LISTENING:
        if playback.session is not None and not playback.is_playing:
            playback.resume(sync=False)
        menu.update_playback(playback.current_time, playback.is_playing)
        return None

    if command.type == CommandType.HOME:
        return None

    if command.type == CommandType.CLEAR_LAST_PLAYBACK:
        clear_last_playback()
        return None

    if command.type == CommandType.SET_BLUETOOTH_ENABLED:
        menu.set_bluetooth_enabled(command.bluetooth_enabled)
        if bluetooth_results is not None:
            start_bluetooth_power_worker(command.bluetooth_enabled, bluetooth_results)
            return BLUETOOTH_POWER_FRAME
        result = set_bluetooth_power(command.bluetooth_enabled)
        menu.set_bluetooth_enabled(result.enabled if result.enabled is not None else command.bluetooth_enabled)
        if result.success:
            playback.refresh_audio_output()
        return bluetooth_result_frame(result)

    if command.type == CommandType.START_BLUETOOTH_SCAN:
        if bluetooth_results is not None:
            start_bluetooth_scan_worker(bluetooth_results)
            return BLUETOOTH_PAIRING_FRAME
        result = scan_bluetooth_devices()
        menu.set_bluetooth_enabled(result.enabled if result.enabled is not None else True)
        if result.devices:
            menu.set_bluetooth_devices([(device.address, device.name) for device in result.devices])
            return None
        return bluetooth_result_frame(result)

    if command.type == CommandType.PAIR_BLUETOOTH_DEVICE:
        device = BluetoothDevice(command.bluetooth_device_address, command.bluetooth_device_name)
        if bluetooth_results is not None:
            start_bluetooth_pairing_worker(device, bluetooth_results)
            return TwoLineFrame("Pairing", command.bluetooth_device_name)
        result = pair_bluetooth_device(device)
        menu.set_bluetooth_enabled(result.enabled if result.enabled is not None else True)
        if result.success:
            playback.refresh_audio_output()
        return bluetooth_result_frame(result)

    if command.type == CommandType.UNPAIR_BLUETOOTH_DEVICE:
        if bluetooth_results is not None:
            start_bluetooth_unpair_worker(bluetooth_results)
            return TwoLineFrame("Unpairing", "Bluetooth device")
        result = unpair_connected_bluetooth_audio_device()
        if result.connected is not None:
            menu.set_bluetooth_connected(result.connected)
        if result.success:
            playback.refresh_audio_output()
        return bluetooth_result_frame(result)

    return None


def start_play_book_worker(
    command: MenuCommand,
    playback: GStreamerPlayback,
    playback_results: queue.SimpleQueue[PlaybackCommandResult],
) -> None:
    def run() -> None:
        playback_results.put(play_book_command_result(command, playback))

    threading.Thread(target=run, daemon=True).start()


def start_bluetooth_power_worker(
    enabled: bool,
    bluetooth_results: queue.SimpleQueue[BluetoothActionResult],
) -> None:
    def run() -> None:
        try:
            bluetooth_results.put(set_bluetooth_power(enabled))
        except Exception:
            print("Bluetooth power worker failed:")
            traceback.print_exc()
            bluetooth_results.put(BluetoothActionResult(False, "Bluetooth error", enabled=None))

    threading.Thread(target=run, daemon=True).start()


def start_bluetooth_pairing_worker(
    device: BluetoothDevice,
    bluetooth_results: queue.SimpleQueue[BluetoothActionResult],
) -> None:
    def run() -> None:
        try:
            bluetooth_results.put(pair_bluetooth_device(device))
        except Exception:
            print("Bluetooth pairing worker failed:")
            traceback.print_exc()
            bluetooth_results.put(BluetoothActionResult(False, "Pairing error", enabled=True))

    threading.Thread(target=run, daemon=True).start()


def start_bluetooth_unpair_worker(
    bluetooth_results: queue.SimpleQueue[BluetoothActionResult],
) -> None:
    def run() -> None:
        try:
            bluetooth_results.put(unpair_connected_bluetooth_audio_device())
        except Exception:
            print("Bluetooth unpair worker failed:")
            traceback.print_exc()
            bluetooth_results.put(BluetoothActionResult(False, "Unpairing error", enabled=True, connected=True))

    threading.Thread(target=run, daemon=True).start()


def start_bluetooth_scan_worker(
    bluetooth_results: queue.SimpleQueue[BluetoothActionResult],
) -> None:
    def run() -> None:
        try:
            bluetooth_results.put(scan_bluetooth_devices())
        except Exception:
            print("Bluetooth scan worker failed:")
            traceback.print_exc()
            bluetooth_results.put(BluetoothActionResult(False, "Scan error", enabled=True))

    threading.Thread(target=run, daemon=True).start()


def play_book_command_result(command: MenuCommand, playback: GStreamerPlayback) -> PlaybackCommandResult:
    try:
        config = load_config()
        podcast = podcast_by_book_id(command.book_id, config.podcasts)
        if podcast is not None:
            session = latest_podcast_session(
                podcast,
                resume_time=command.resume_time,
                start_over=command.start_over,
            )
            client = PodcastProgressClient()
            playback.start(session, client)
            return PlaybackCommandResult(session=session, client=client)

        if not config.is_ready:
            return PlaybackCommandResult(error_frame=setup_address_frame())
        client = client_from_config(config, AudiobookshelfClient)
        session = client.start_playback(
            command.book_id,
            start_over=command.start_over,
            resume_time=command.resume_time,
        )
        playback.start(session, client)
        return PlaybackCommandResult(session=session, client=client)
    except (AudiobookshelfError, PlaybackError, PodcastError) as error:
        print(f"Playback failed: {error}")
        return PlaybackCommandResult(error_frame=TwoLineFrame("Could not play", "Check setup"))


def should_return_to_active_session(command: MenuCommand, playback: GStreamerPlayback) -> bool:
    return (
        not command.start_over
        and playback.session is not None
        and playback.is_playing
        and playback.session.library_item_id == command.book_id
    )


def handle_input_events_with_fallback(
    events: queue.SimpleQueue[InputEvent],
    mixer_controls: tuple[str, ...] = DEFAULT_MIXER_CONTROLS,
    fallback_percent: int = 50,
    fallback_muted: bool = False,
) -> tuple[DisplayFrame | None, int, bool]:
    frame: DisplayFrame | None = None
    while True:
        try:
            event = events.get_nowait()
        except queue.Empty:
            return frame, fallback_percent, fallback_muted

        try:
            if event.name == "volume":
                state = change_volume(event.steps, controls=mixer_controls)
                fallback_percent = state.percent
                fallback_muted = state.muted
                frame = volume_frame_for_state(state)
            elif event.name == "volume_click":
                was_effectively_muted = effective_muted(fallback_percent, fallback_muted)
                state = toggle_mute(controls=mixer_controls)
                if was_effectively_muted and effective_muted(state.percent, state.muted):
                    state = restored_audible_volume_state(mixer_controls)
                fallback_percent = state.percent
                fallback_muted = state.muted
                frame = volume_frame_for_state(state)
            elif event.name == "show_ip":
                frame = setup_address_frame()
        except AudioError as error:
            print(f"Volume control failed: {error}")
            if event.name == "volume":
                fallback_percent = min(max(fallback_percent + event.steps * 5, 0), 100)
                fallback_muted = False
                frame = VolumeFrame(fallback_percent, muted=fallback_percent <= 0)
            elif event.name == "volume_click":
                if effective_muted(fallback_percent, fallback_muted) and fallback_percent <= 0:
                    fallback_percent = DEFAULT_UNMUTE_VOLUME_PERCENT
                    fallback_muted = False
                else:
                    fallback_muted = not fallback_muted
                frame = VolumeFrame(fallback_percent, muted=fallback_muted or fallback_percent <= 0)
            elif event.name == "show_ip":
                frame = setup_address_frame()


def sleep_until_shutdown(shutdown: Shutdown, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while not shutdown.requested and time.monotonic() < deadline:
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def signal_boot_splash_handoff(
    path: str = DEFAULT_BOOT_SPLASH_HANDOFF_PATH,
    settle_seconds: float = DEFAULT_BOOT_SPLASH_HANDOFF_SETTLE_SECONDS,
) -> None:
    try:
        Path(path).write_text("starting\n", encoding="utf-8")
    except OSError as error:
        print(f"Boot splash handoff marker could not be written: {error}")
        return
    if settle_seconds > 0:
        time.sleep(settle_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Chapter Player for Audiobookshelf OLED status service.")
    parser.add_argument("--spi-bus", type=int, default=0)
    parser.add_argument("--spi-device", type=int, default=0)
    parser.add_argument("--dc-pin", type=int, default=24)
    parser.add_argument("--reset-pin", type=int, default=25)
    parser.add_argument("--cs-pin", type=int, default=None)
    parser.add_argument("--speed", type=int, default=1_000_000)
    parser.add_argument("--refresh-seconds", type=float, default=DEFAULT_REFRESH_SECONDS)
    parser.add_argument("--status-refresh-seconds", type=float, default=DEFAULT_STATUS_REFRESH_SECONDS)
    parser.add_argument("--splash-seconds", type=float, default=DEFAULT_SPLASH_SECONDS)
    parser.add_argument(
        "--startup-network-grace-seconds",
        type=float,
        default=DEFAULT_STARTUP_NETWORK_GRACE_SECONDS,
    )
    parser.add_argument("--home-refresh-seconds", type=float, default=DEFAULT_HOME_REFRESH_SECONDS)
    parser.add_argument("--no-nav-input", action="store_true")
    parser.add_argument("--nav-clk-pin", type=int, default=5)
    parser.add_argument("--nav-dt-pin", type=int, default=6)
    parser.add_argument("--nav-sw-pin", type=int, default=13)
    nav_direction = parser.add_mutually_exclusive_group()
    nav_direction.add_argument("--nav-normal-direction", dest="nav_reversed", action="store_false")
    nav_direction.add_argument("--nav-reversed", dest="nav_reversed", action="store_true")
    parser.set_defaults(nav_reversed=True)
    parser.add_argument("--no-volume-input", action="store_true")
    parser.add_argument("--volume-clk-pin", type=int, default=12)
    parser.add_argument("--volume-dt-pin", type=int, default=16)
    parser.add_argument("--volume-sw-pin", type=int, default=26)
    parser.add_argument("--volume-normal-direction", action="store_true")
    parser.add_argument("--mixer-control", action="append", default=None)
    parser.add_argument("--system-volume-control", action="store_true")
    parser.add_argument("--amp-shutdown-pin", type=int, default=None)
    parser.add_argument("--screen-saver-idle-seconds", type=float, default=DEFAULT_SCREEN_SAVER_IDLE_SECONDS)
    parser.add_argument("--screen-saver-fps", type=float, default=DEFAULT_SCREEN_SAVER_FRAMES_PER_SECOND)
    parser.add_argument("--no-screen-saver", action="store_true")
    parser.add_argument("--boot-splash-handoff-path", default=DEFAULT_BOOT_SPLASH_HANDOFF_PATH)
    parser.add_argument("--boot-splash-handoff-settle-seconds", type=float, default=DEFAULT_BOOT_SPLASH_HANDOFF_SETTLE_SECONDS)
    args = parser.parse_args()

    if args.boot_splash_handoff_path:
        signal_boot_splash_handoff(
            args.boot_splash_handoff_path,
            settle_seconds=args.boot_splash_handoff_settle_seconds,
        )

    display = Sh1122Display(
        spi_bus=args.spi_bus,
        spi_device=args.spi_device,
        dc_pin=args.dc_pin,
        reset_pin=args.reset_pin,
        cs_pin=args.cs_pin,
        max_speed_hz=args.speed,
    )
    run_oled_service(
        display,
        refresh_seconds=args.refresh_seconds,
        status_refresh_seconds=args.status_refresh_seconds,
        splash_seconds=args.splash_seconds,
        startup_network_grace_seconds=args.startup_network_grace_seconds,
        home_refresh_seconds=args.home_refresh_seconds,
        nav_input_enabled=not args.no_nav_input,
        nav_pins=Ky040Pins(
            clk=args.nav_clk_pin,
            dt=args.nav_dt_pin,
            sw=args.nav_sw_pin,
            reversed=args.nav_reversed,
        ),
        volume_input_enabled=not args.no_volume_input,
        volume_pins=Ky040Pins(
            clk=args.volume_clk_pin,
            dt=args.volume_dt_pin,
            sw=args.volume_sw_pin,
            reversed=not args.volume_normal_direction,
        ),
        mixer_controls=tuple(args.mixer_control or DEFAULT_MIXER_CONTROLS),
        screen_saver_idle_seconds=0.0 if args.no_screen_saver else args.screen_saver_idle_seconds,
        screen_saver_frames_per_second=args.screen_saver_fps,
        amp_shutdown_pin=args.amp_shutdown_pin,
        software_volume_only=not args.system_volume_control,
    )


if __name__ == "__main__":
    main()
