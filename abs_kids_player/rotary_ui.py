from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Union

from .config import LIBRARY_SORT_AUTHOR, LIBRARY_SORT_TITLE, valid_library_sort_mode
from .models import Book, Chapter, PlaybackSession
from .player_state import LastPlaybackState


BLUETOOTH_DEVICE_NAME_MAX_CHARS = 20


class Screen(str, Enum):
    LIBRARY = "library"
    STARTUP_RESUME = "startup_resume"
    RESUME_CHOICE = "resume_choice"
    PLAYING = "playing"
    CHAPTER_CONFIRM = "chapter_confirm"
    SLEEP_CONFIRM = "sleep_confirm"
    BLUETOOTH = "bluetooth"
    BLUETOOTH_DEVICES = "bluetooth_devices"


class CommandType(str, Enum):
    PLAY_BOOK = "play_book"
    PAUSE_PLAYBACK = "pause_playback"
    TOGGLE_PLAYBACK = "toggle_playback"
    SEEK_CHAPTER = "seek_chapter"
    HOME = "home"
    VOLUME_DELTA = "volume_delta"
    TOGGLE_MUTE = "toggle_mute"
    SHOW_IP = "show_ip"
    CLEAR_LAST_PLAYBACK = "clear_last_playback"
    SET_BLUETOOTH_ENABLED = "set_bluetooth_enabled"
    START_BLUETOOTH_SCAN = "start_bluetooth_scan"
    PAIR_BLUETOOTH_DEVICE = "pair_bluetooth_device"
    UNPAIR_BLUETOOTH_DEVICE = "unpair_bluetooth_device"
    CONFIRM_STILL_LISTENING = "confirm_still_listening"


@dataclass(frozen=True)
class MenuCommand:
    type: CommandType
    book_id: str = ""
    start_over: bool = False
    resume_time: float = 0
    chapter_index: int = 0
    seek_time: float = 0
    volume_delta: int = 0
    display_seconds: int = 0
    bluetooth_enabled: bool = False
    bluetooth_device_address: str = ""
    bluetooth_device_name: str = ""


@dataclass(frozen=True)
class TwoLineFrame:
    top: str
    bottom: str
    muted: bool = False
    bluetooth_connected: bool = False


@dataclass(frozen=True)
class HomeFrame:
    title: str
    author: str
    series_position: str = ""
    title_scroll_px: int = 0
    title_scrolling: bool = False
    section_letter: str = ""
    section_letter_fill: int = 0
    muted: bool = False
    bluetooth_connected: bool = False
    is_podcast: bool = False

    @property
    def top(self) -> str:
        return self.title

    @property
    def bottom(self) -> str:
        return author_line(self.author)


@dataclass(frozen=True)
class SplashFrame:
    text: str

    @property
    def top(self) -> str:
        return self.text

    @property
    def bottom(self) -> str:
        return ""


@dataclass(frozen=True)
class ScreenSaverFrame:
    frame_index: int
    mode: str = "chapter"
    words: tuple[str, ...] = ("chapter",)
    clock_text: str = ""
    brightness_percent: int = 15

    @property
    def top(self) -> str:
        return "Screen saver"

    @property
    def bottom(self) -> str:
        return ""


@dataclass(frozen=True)
class VolumeFrame:
    percent: int
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return "Muted" if self.is_muted else "Volume"

    @property
    def bottom(self) -> str:
        return volume_bar(self.percent)

    @property
    def is_muted(self) -> bool:
        return self.muted or self.percent <= 0


@dataclass(frozen=True)
class PlayingFrame:
    chapter_text: str
    remaining_text: str
    actions: tuple[str, str, str, str]
    selected_index: int
    title_scroll_px: int = 0
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return f"{self.chapter_text} {self.remaining_text}".strip()

    @property
    def bottom(self) -> str:
        parts = list(self.actions)
        parts[self.selected_index] = f"[{parts[self.selected_index]}]"
        return " ".join(parts)


@dataclass(frozen=True)
class ChapterConfirmFrame:
    direction: str
    selected_index: int = 0
    options: tuple[str, str] = ("Yes", "No")
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return f"Are you sure you want to listen to the {self.direction} chapter?"

    @property
    def bottom(self) -> str:
        parts = list(self.options)
        parts[self.selected_index] = f"[{parts[self.selected_index]}]"
        return " ".join(parts)


@dataclass(frozen=True)
class SleepConfirmFrame:
    countdown_seconds: int
    options: tuple[str, ...] = ("Yes",)
    selected_index: int = 0
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return f"Are you still listening? {max(0, self.countdown_seconds)}"

    @property
    def bottom(self) -> str:
        return "[Yes]"


@dataclass(frozen=True)
class ResumeChoiceFrame:
    title: str
    selected_index: int = 0
    options: tuple[str, ...] = ("Continue", "Start over")
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return self.title

    @property
    def bottom(self) -> str:
        parts = list(self.options)
        parts[self.selected_index] = f"[{parts[self.selected_index]}]"
        return " ".join(parts)


@dataclass(frozen=True)
class StartupResumeFrame:
    title: str
    selected_index: int = 0
    options: tuple[str, str] = ("Continue", "Home")
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return f"You were listening to {self.title}"

    @property
    def bottom(self) -> str:
        parts = list(self.options)
        parts[self.selected_index] = f"[{parts[self.selected_index]}]"
        return " ".join(parts)


@dataclass(frozen=True)
class BluetoothMenuFrame:
    enabled: bool
    selected_index: int = 2
    options: tuple[str, str, str] = ("Back", "Disable", "Pair")
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return "Bluetooth On" if self.enabled else "Bluetooth Off"

    @property
    def bottom(self) -> str:
        parts = list(self.options)
        parts[self.selected_index] = f"[{parts[self.selected_index]}]"
        return " ".join(parts)


@dataclass(frozen=True)
class BluetoothDevicesFrame:
    device_name: str
    selected_index: int
    total_count: int
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return "Bluetooth Devices"

    @property
    def bottom(self) -> str:
        suffix = f" {self.selected_index + 1}/{self.total_count}" if self.total_count else ""
        return f"{shorten_device_name(self.device_name)}{suffix}".strip()


@dataclass(frozen=True)
class WifiSetupFrame:
    ssid: str
    url: str
    muted: bool = False
    bluetooth_connected: bool = False

    @property
    def top(self) -> str:
        return f"Connect to {self.ssid}"

    @property
    def bottom(self) -> str:
        return f"Browse to {self.url}"


DisplayFrame = Union[
    TwoLineFrame,
    HomeFrame,
    SplashFrame,
    ScreenSaverFrame,
    VolumeFrame,
    PlayingFrame,
    ChapterConfirmFrame,
    SleepConfirmFrame,
    ResumeChoiceFrame,
    StartupResumeFrame,
    BluetoothMenuFrame,
    BluetoothDevicesFrame,
    WifiSetupFrame,
]


PLAYING_ACTIONS = ["Home", "Prev", "Play", "Next"]
PLAYING_PLAY_INDEX = 2
VOLUME_STEP_PERCENT = 5
VOLUME_OVERLAY_SECONDS = 3
PLAYING_TITLE_WIDTH = 18
CHAPTER_CONFIRM_TIMEOUT_SECONDS = 5.0
SECTION_LETTER_HOLD_SECONDS = 1.0
SECTION_LETTER_FADE_SECONDS = 0.8
SECTION_LETTER_MAX_FILL = 255
IGNORED_TITLE_PREFIX_WORDS = {"a", "the"}
POWER_OFF_RESUME_REWIND_SECONDS = 10.0


class ApplianceMenu:
    def __init__(
        self,
        books: list[Book] | None = None,
        library_sort_mode: str = LIBRARY_SORT_TITLE,
    ) -> None:
        self.books = books or []
        self.library_sort_mode = valid_library_sort_mode(library_sort_mode)
        self.screen = Screen.LIBRARY
        self.book_index = 0
        self.resume_choice_index = 0
        self.startup_resume_state: LastPlaybackState | None = None
        self.startup_resume_index = 0
        self.confirm_yes = True
        self.chapter_confirm_direction = "next"
        self.chapter_confirm_elapsed = 0.0
        self.pending_chapter_index = 0
        self.sleep_confirm_seconds = 30
        self.bluetooth_enabled = True
        self.bluetooth_connected = False
        self.bluetooth_index = 2
        self.bluetooth_return_screen = Screen.LIBRARY
        self.bluetooth_devices: list[tuple[str, str]] = []
        self.bluetooth_device_index = 0
        self.session: PlaybackSession | None = None
        self.current_time = 0.0
        self.is_playing = False
        self.playing_action_index = PLAYING_PLAY_INDEX
        self.volume_percent = 50
        self.volume_overlay_remaining = 0
        self.title_scroll_position = 0
        self._title_scroll_elapsed = 0.0
        self._title_scroll_subject = ""
        self.section_letter = ""
        self.section_letter_fill = 0
        self._section_letter_elapsed = 0.0

    def set_books(self, books: list[Book]) -> None:
        self.books = books
        self.book_index = min(self.book_index, max(0, len(books) - 1))
        if not books:
            self.clear_section_letter()
            self.screen = Screen.LIBRARY

    def set_library_sort_mode(self, mode: str) -> None:
        self.library_sort_mode = valid_library_sort_mode(mode)
        self.clear_section_letter()

    def reset_to_library(self) -> None:
        self.session = None
        self.current_time = 0.0
        self.is_playing = False
        self.book_index = min(self.book_index, max(0, len(self.books) - 1))
        self.playing_action_index = PLAYING_PLAY_INDEX
        self.startup_resume_state = None
        self.startup_resume_index = 0
        self.resume_choice_index = 0
        self.pending_chapter_index = 0
        self.confirm_yes = True
        self.chapter_confirm_elapsed = 0.0
        self.sleep_confirm_seconds = 30
        self.screen = Screen.LIBRARY
        self.reset_title_scroll()
        self.clear_section_letter()

    def set_session(self, session: PlaybackSession, is_playing: bool = True) -> None:
        self.session = session
        self.current_time = session.current_time
        self.is_playing = is_playing
        self.playing_action_index = PLAYING_PLAY_INDEX
        self.reset_title_scroll()
        self.screen = Screen.PLAYING

    def set_startup_resume(self, state: LastPlaybackState | None) -> None:
        self.startup_resume_state = state if state and state.is_ready else None
        self.startup_resume_index = 0
        if self.startup_resume_state is not None:
            self.screen = Screen.STARTUP_RESUME

    def update_playback(self, current_time: float, is_playing: bool) -> None:
        self.current_time = max(0, current_time)
        self.is_playing = is_playing

    def rotate_nav(self, steps: int) -> list[MenuCommand]:
        if steps == 0:
            return []
        direction = 1 if steps > 0 else -1
        for _ in range(abs(steps)):
            self.rotate_nav_once(direction)
        return []

    def rotate_nav_once(self, direction: int) -> None:
        if self.screen == Screen.LIBRARY:
            self.book_index = wrap_index(self.book_index + direction, len(self.books))
            self.show_section_letter()
        elif self.screen == Screen.STARTUP_RESUME:
            self.startup_resume_index = clamp(self.startup_resume_index + direction, 0, 1)
        elif self.screen == Screen.RESUME_CHOICE:
            self.resume_choice_index = clamp(
                self.resume_choice_index + direction,
                0,
                len(self.resume_options) - 1,
            )
        elif self.screen == Screen.PLAYING:
            self.playing_action_index = clamp(
                self.playing_action_index + direction,
                0,
                len(PLAYING_ACTIONS) - 1,
            )
        elif self.screen == Screen.CHAPTER_CONFIRM:
            selected_index = 0 if self.confirm_yes else 1
            selected_index = clamp(selected_index + direction, 0, 1)
            self.confirm_yes = selected_index == 0
            self.chapter_confirm_elapsed = 0.0
        elif self.screen == Screen.BLUETOOTH:
            self.bluetooth_index = clamp(self.bluetooth_index + direction, 0, 2)
        elif self.screen == Screen.BLUETOOTH_DEVICES:
            self.bluetooth_device_index = clamp(
                self.bluetooth_device_index + direction,
                0,
                max(0, len(self.bluetooth_device_options) - 1),
            )

    def click_nav(self) -> list[MenuCommand]:
        if self.screen == Screen.LIBRARY:
            if self.books:
                self.resume_choice_index = self.default_resume_choice_index
                self.screen = Screen.RESUME_CHOICE
            return []

        if self.screen == Screen.STARTUP_RESUME:
            state = self.startup_resume_state
            self.startup_resume_state = None
            self.screen = Screen.LIBRARY
            if self.startup_resume_index == 1 or state is None:
                return [MenuCommand(CommandType.CLEAR_LAST_PLAYBACK)]
            return [
                MenuCommand(
                    CommandType.PLAY_BOOK,
                    book_id=state.book_id,
                    start_over=False,
                    resume_time=power_off_resume_time(state.current_time),
                )
            ]

        if self.screen == Screen.RESUME_CHOICE:
            book = self.books[self.book_index]
            choice = self.resume_options[self.resume_choice_index]
            if choice == "Home":
                self.screen = Screen.LIBRARY
                return [MenuCommand(CommandType.HOME)]
            start_over = choice in ("Start", "Start over")
            resume_time = 0 if start_over else book.current_time
            return [
                MenuCommand(
                    CommandType.PLAY_BOOK,
                    book_id=book.id,
                    start_over=start_over,
                    resume_time=resume_time,
                )
            ]

        if self.screen == Screen.PLAYING:
            action = self.playing_action
            if action == "Home":
                self.screen = Screen.LIBRARY
                return [MenuCommand(CommandType.HOME)]
            if action == "Prev":
                self.queue_chapter_jump(-1)
                return []
            if action == "Next":
                self.queue_chapter_jump(1)
                return []
            return [MenuCommand(CommandType.TOGGLE_PLAYBACK)]

        if self.screen == Screen.CHAPTER_CONFIRM:
            if not self.confirm_yes:
                self.screen = Screen.PLAYING
                return []
            chapter = self.chapters[self.pending_chapter_index]
            self.current_time = chapter.start
            self.screen = Screen.PLAYING
            return [
                MenuCommand(
                    CommandType.SEEK_CHAPTER,
                    chapter_index=self.pending_chapter_index,
                    seek_time=chapter.start,
                )
            ]

        if self.screen == Screen.SLEEP_CONFIRM:
            self.screen = Screen.PLAYING if self.session is not None else Screen.LIBRARY
            return [MenuCommand(CommandType.CONFIRM_STILL_LISTENING)]

        if self.screen == Screen.BLUETOOTH:
            option = self.bluetooth_options[self.bluetooth_index]
            if option == "Back":
                self.screen = self.bluetooth_return_screen
                return []
            if option in ("Enable", "Disable"):
                self.bluetooth_enabled = option == "Enable"
                return [
                    MenuCommand(
                        CommandType.SET_BLUETOOTH_ENABLED,
                        bluetooth_enabled=self.bluetooth_enabled,
                    )
                ]
            if option == "Pair":
                commands = []
                if not self.bluetooth_enabled:
                    self.bluetooth_enabled = True
                    commands.append(
                        MenuCommand(CommandType.SET_BLUETOOTH_ENABLED, bluetooth_enabled=True)
                    )
                commands.append(MenuCommand(CommandType.START_BLUETOOTH_SCAN))
                return commands
            if option == "Unpair":
                return [MenuCommand(CommandType.UNPAIR_BLUETOOTH_DEVICE)]

        if self.screen == Screen.BLUETOOTH_DEVICES:
            address, name = self.bluetooth_device_options[self.bluetooth_device_index]
            if not address:
                self.screen = Screen.BLUETOOTH
                return []
            return [
                MenuCommand(
                    CommandType.PAIR_BLUETOOTH_DEVICE,
                    bluetooth_device_address=address,
                    bluetooth_device_name=name,
                )
            ]

        return []

    def rotate_volume(self, steps: int) -> list[MenuCommand]:
        if steps == 0:
            return []
        self.volume_percent = clamp(
            self.volume_percent + steps * VOLUME_STEP_PERCENT,
            0,
            100,
        )
        self.volume_overlay_remaining = VOLUME_OVERLAY_SECONDS
        return [MenuCommand(CommandType.VOLUME_DELTA, volume_delta=steps)]

    def click_volume(self) -> list[MenuCommand]:
        return [MenuCommand(CommandType.TOGGLE_MUTE)]

    def hold_volume(self) -> list[MenuCommand]:
        return [MenuCommand(CommandType.SHOW_IP, display_seconds=5)]

    def hold_nav(self, bluetooth_enabled: bool = True, bluetooth_connected: bool = False) -> list[MenuCommand]:
        if self.screen == Screen.SLEEP_CONFIRM:
            return []
        self.open_bluetooth_menu(bluetooth_enabled, bluetooth_connected)
        return [MenuCommand(CommandType.PAUSE_PLAYBACK)]

    def open_bluetooth_menu(self, bluetooth_enabled: bool = True, bluetooth_connected: bool = False) -> None:
        if self.screen != Screen.BLUETOOTH:
            self.bluetooth_return_screen = self.screen
        self.bluetooth_enabled = bluetooth_enabled
        self.bluetooth_connected = bluetooth_connected
        self.bluetooth_index = 2 if bluetooth_enabled else 1
        self.screen = Screen.BLUETOOTH

    def set_bluetooth_enabled(self, enabled: bool) -> None:
        self.bluetooth_enabled = enabled
        if not enabled:
            self.bluetooth_connected = False
        self.bluetooth_index = min(self.bluetooth_index, len(self.bluetooth_options) - 1)

    def set_bluetooth_connected(self, connected: bool) -> None:
        self.bluetooth_connected = connected
        self.bluetooth_index = min(self.bluetooth_index, len(self.bluetooth_options) - 1)

    def set_bluetooth_devices(self, devices: list[tuple[str, str]]) -> None:
        self.bluetooth_devices = devices
        self.bluetooth_device_index = 1 if devices else 0
        self.screen = Screen.BLUETOOTH_DEVICES

    def close_bluetooth_menu(self) -> None:
        self.screen = self.bluetooth_return_screen

    def render(self) -> DisplayFrame:
        if self.volume_overlay_remaining > 0:
            return self.render_volume()

        if self.screen == Screen.LIBRARY:
            if not self.books:
                return TwoLineFrame("No books", "Check connection")
            book = self.books[self.book_index]
            return HomeFrame(
                book.display_title,
                book.author,
                series_position=book.series_position,
                section_letter=self.section_letter,
                section_letter_fill=self.section_letter_fill,
                is_podcast=book_is_podcast(book),
            )

        if self.screen == Screen.STARTUP_RESUME and self.startup_resume_state is not None:
            return StartupResumeFrame(
                self.startup_resume_state.title,
                selected_index=self.startup_resume_index,
            )

        if self.screen == Screen.RESUME_CHOICE:
            book = self.books[self.book_index]
            return ResumeChoiceFrame(book.display_title, self.resume_choice_index, self.resume_options)

        if self.screen == Screen.PLAYING and self.session:
            return PlayingFrame(
                chapter_text=self.playing_chapter_text,
                remaining_text=self.remaining_text,
                actions=self.playing_actions,
                selected_index=self.playing_action_index,
                title_scroll_px=self.title_scroll_position,
            )

        if self.screen == Screen.CHAPTER_CONFIRM and self.session:
            return ChapterConfirmFrame(
                direction=self.chapter_confirm_direction,
                selected_index=0 if self.confirm_yes else 1,
            )

        if self.screen == Screen.SLEEP_CONFIRM:
            return SleepConfirmFrame(self.sleep_confirm_seconds)

        if self.screen == Screen.BLUETOOTH:
            return BluetoothMenuFrame(
                enabled=self.bluetooth_enabled,
                selected_index=self.bluetooth_index,
                options=self.bluetooth_options,
            )

        if self.screen == Screen.BLUETOOTH_DEVICES:
            options = self.bluetooth_device_options
            index = min(self.bluetooth_device_index, max(0, len(options) - 1))
            _address, name = options[index]
            return BluetoothDevicesFrame(name, index, len(options))

        return TwoLineFrame("Loading", "")

    @property
    def bluetooth_options(self) -> tuple[str, str, str]:
        return (
            "Back",
            "Disable" if self.bluetooth_enabled else "Enable",
            "Unpair" if self.bluetooth_connected else "Pair",
        )

    @property
    def bluetooth_device_options(self) -> list[tuple[str, str]]:
        return [("", "Back"), *self.bluetooth_devices]

    def render_volume(self) -> VolumeFrame:
        return VolumeFrame(self.volume_percent, muted=self.volume_percent <= 0)

    def tick_overlay(self, seconds: int = 1) -> None:
        self.volume_overlay_remaining = max(0, self.volume_overlay_remaining - seconds)

    def tick_title_scroll(self, steps: int = 1) -> None:
        if self.screen != Screen.PLAYING or not self.session:
            return
        self.title_scroll_position = max(0, self.title_scroll_position + steps)

    def tick_chapter_confirm_timeout(
        self,
        elapsed_seconds: float,
        timeout_seconds: float = CHAPTER_CONFIRM_TIMEOUT_SECONDS,
    ) -> bool:
        if self.screen != Screen.CHAPTER_CONFIRM:
            self.chapter_confirm_elapsed = 0.0
            return False
        self.chapter_confirm_elapsed += max(0.0, elapsed_seconds)
        if self.chapter_confirm_elapsed < timeout_seconds:
            return False
        self.chapter_confirm_elapsed = 0.0
        self.screen = Screen.PLAYING
        return True

    def show_sleep_confirmation(self, countdown_seconds: int = 30) -> None:
        self.sleep_confirm_seconds = max(0, countdown_seconds)
        self.playing_action_index = PLAYING_PLAY_INDEX
        self.screen = Screen.SLEEP_CONFIRM

    def update_sleep_confirmation(self, countdown_seconds: int) -> None:
        if self.screen == Screen.SLEEP_CONFIRM:
            self.sleep_confirm_seconds = max(0, countdown_seconds)

    def dismiss_sleep_confirmation(self) -> None:
        if self.screen == Screen.SLEEP_CONFIRM:
            self.screen = Screen.PLAYING if self.session is not None else Screen.LIBRARY

    def tick_section_letter(
        self,
        elapsed_seconds: float,
        hold_seconds: float = SECTION_LETTER_HOLD_SECONDS,
        fade_seconds: float = SECTION_LETTER_FADE_SECONDS,
    ) -> None:
        if not self.section_letter:
            return

        self._section_letter_elapsed += max(0.0, elapsed_seconds)
        if self._section_letter_elapsed <= hold_seconds:
            self.section_letter_fill = SECTION_LETTER_MAX_FILL
            return

        if fade_seconds <= 0:
            self.clear_section_letter()
            return

        fade_elapsed = self._section_letter_elapsed - hold_seconds
        if fade_elapsed >= fade_seconds:
            self.clear_section_letter()
            return

        progress = fade_elapsed / fade_seconds
        self.section_letter_fill = round(SECTION_LETTER_MAX_FILL * (1.0 - progress))

    def update_title_scroll(
        self,
        elapsed_seconds: float,
        delay_seconds: float,
        pixels_per_second: float,
    ) -> None:
        if self.screen != Screen.PLAYING or not self.session:
            self.reset_title_scroll()
            return

        chapter_text = self.playing_chapter_text
        if chapter_text != self._title_scroll_subject:
            self.reset_title_scroll(chapter_text)

        self._title_scroll_elapsed += max(0.0, elapsed_seconds)
        if self._title_scroll_elapsed < delay_seconds:
            self.title_scroll_position = 0
            return

        active_seconds = self._title_scroll_elapsed - delay_seconds
        self.title_scroll_position = max(0, round(active_seconds * pixels_per_second))

    def reset_title_scroll(self, subject: str = "") -> None:
        self.title_scroll_position = 0
        self._title_scroll_elapsed = 0.0
        self._title_scroll_subject = subject

    def show_section_letter(self) -> None:
        if not self.books:
            self.clear_section_letter()
            return
        book = self.books[self.book_index]
        self.section_letter = (
            author_section_letter(book.author)
            if self.library_sort_mode == LIBRARY_SORT_AUTHOR
            else title_section_letter(book.display_title)
        )
        self.section_letter_fill = SECTION_LETTER_MAX_FILL
        self._section_letter_elapsed = 0.0

    def clear_section_letter(self) -> None:
        self.section_letter = ""
        self.section_letter_fill = 0
        self._section_letter_elapsed = 0.0

    def queue_chapter_jump(self, direction: int) -> None:
        if not self.session or not self.chapters:
            return
        current_index = self.current_chapter_index
        next_index = min(max(current_index + direction, 0), len(self.chapters) - 1)
        if next_index == current_index:
            return
        self.pending_chapter_index = next_index
        self.confirm_yes = True
        self.chapter_confirm_direction = "previous" if direction < 0 else "next"
        self.chapter_confirm_elapsed = 0.0
        self.screen = Screen.CHAPTER_CONFIRM

    @property
    def chapters(self) -> list[Chapter]:
        if not self.session:
            return []
        return self.session.chapters

    @property
    def current_chapter_index(self) -> int:
        for index, chapter in enumerate(self.chapters):
            if chapter.start <= self.current_time < chapter.end:
                return index
        return max(0, len(self.chapters) - 1)

    @property
    def current_chapter(self) -> Chapter:
        if not self.chapters:
            return Chapter(index=1, title="Chapter", start=0, end=0)
        return self.chapters[self.current_chapter_index]

    @property
    def playing_action(self) -> str:
        return PLAYING_ACTIONS[self.playing_action_index]

    @property
    def action_row(self) -> str:
        actions = list(self.playing_actions)
        actions[self.playing_action_index] = f"[{actions[self.playing_action_index]}]"
        return " ".join(actions)

    @property
    def playing_actions(self) -> tuple[str, str, str, str]:
        actions = PLAYING_ACTIONS.copy()
        actions[PLAYING_PLAY_INDEX] = "Pause" if self.is_playing else "Play"
        return tuple(actions)

    @property
    def playing_chapter_text(self) -> str:
        if not self.session:
            return ""
        return self.current_chapter.title

    @property
    def remaining_text(self) -> str:
        if not self.session:
            return ""
        remaining = max(0, self.session.duration - self.current_time)
        return f"-{format_time(remaining)}"

    @property
    def resume_options(self) -> tuple[str, ...]:
        if not self.books:
            return ("Home",)
        if self.books[self.book_index].has_play_history:
            return ("Home", "Continue", "Start over")
        return ("Home", "Start")

    @property
    def default_resume_choice_index(self) -> int:
        return 1 if len(self.resume_options) > 1 else 0


def wrap_index(index: int, count: int) -> int:
    if count <= 0:
        return 0
    return index % count


def clamp(value: int, minimum: int, maximum: int) -> int:
    return min(max(value, minimum), maximum)


def volume_bar(percent: int, width: int = 12) -> str:
    percent = clamp(percent, 0, 100)
    filled = round((percent / 100) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def author_line(author: str) -> str:
    author = author.strip()
    return f"By {author}" if author else ""


def shorten_device_name(name: str, max_chars: int = BLUETOOTH_DEVICE_NAME_MAX_CHARS) -> str:
    clean = " ".join(name.split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 3)].rstrip() + "..."


def title_section_letter(title: str) -> str:
    words = title_words(title)
    for word in words:
        if word.lower() not in IGNORED_TITLE_PREFIX_WORDS:
            return section_letter_for_word(word)
    if words:
        return section_letter_for_word(words[0])
    return "#"


def title_sort_text(title: str) -> str:
    words = title_words(title)
    sortable_words = list(words)
    while sortable_words and sortable_words[0].lower() in IGNORED_TITLE_PREFIX_WORDS:
        sortable_words.pop(0)
    if not sortable_words:
        sortable_words = words
    return " ".join(sortable_words).casefold()


def author_sort_text(author: str) -> str:
    clean_author = " ".join(author.split())
    if not clean_author:
        return ""
    primary_author = re.split(r"\s*(?:,|;|&|\band\b)\s*", clean_author, maxsplit=1, flags=re.IGNORECASE)[0]
    name_parts = primary_author.split()
    if not name_parts:
        return ""
    last_name = name_parts[-1].strip(".,")
    given_names = " ".join(name_parts[:-1])
    return f"{last_name} {given_names}".strip().casefold()


def author_section_letter(author: str) -> str:
    sort_text = author_sort_text(author)
    return section_letter_for_word(sort_text) if sort_text else "#"


def title_words(title: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    for character in title.strip():
        if character.isalnum():
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def section_letter_for_word(word: str) -> str:
    first = word[0]
    if first.isdigit():
        return "#"
    return first.upper()


def book_is_podcast(book: Book) -> bool:
    return book.id.startswith("podcast:")


def power_off_resume_time(current_time: float) -> float:
    return max(0.0, current_time - POWER_OFF_RESUME_REWIND_SECONDS)


def marquee_text(text: str, width: int, position: int = 0, gap: int = 3) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    padded = text + " " * gap
    position = position % len(padded)
    doubled = padded + padded
    return doubled[position : position + width]


def marquee_cycle_length(text: str, width: int, gap: int = 3) -> int:
    if len(text) <= width:
        return 1
    return len(text) + gap


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
