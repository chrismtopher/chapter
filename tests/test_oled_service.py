from __future__ import annotations

import unittest
import queue
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from abs_kids_player.api import AudiobookshelfError
from abs_kids_player.config import (
    DEFAULT_SCREEN_SAVER_DIM_PERCENT,
    LIBRARY_SORT_AUTHOR,
    SCREEN_SAVER_BOOKS,
    SCREEN_SAVER_CLOCK,
    AppConfig,
    PodcastConfig,
)
from abs_kids_player.models import AudioTrack, Book, Chapter, PlaybackSession
from abs_kids_player.player_state import load_player_state, save_last_playback
from abs_kids_player.oled_service import (
    BLUETOOTH_PAIRING_FRAME,
    BLUETOOTH_POWER_FRAME,
    BOOK_LOADING_FRAME,
    BookLoadResult,
    DEFAULT_SCREEN_SAVER_IDLE_SECONDS,
    DEFAULT_UNMUTE_VOLUME_PERCENT,
    SOFTWARE_UPDATE_FRAME,
    ListeningSleepTimer,
    bluetooth_pairing_frame,
    bluetooth_result_frame,
    bluetooth_scanning_frame,
    book_load_result,
    clock_screen_saver_text,
    consume_screen_saver_wake_input,
    drain_input_events,
    frame_with_mute_indicator,
    frame_with_status_indicators,
    frame_for_boot_state,
    frame_for_wifi_status,
    home_frame_for_books,
    handle_menu_command,
    handle_oled_input_events,
    handle_web_player_commands,
    handle_input_events_with_fallback,
    input_activity_seen,
    load_library_books,
    load_home_frame,
    pause_and_publish_playback,
    poll_playback_safely,
    refresh_home_cache,
    screen_saver_frame,
    screen_saver_is_active,
    screen_saver_words_for_mode,
    scrolled_home_frame,
    set_amp_shutdown,
    should_return_to_active_session,
    signal_boot_splash_handoff,
    save_playback_state,
    sorted_books_for_menu,
    splash_frame,
    start_book_load_worker,
    unmute_for_audible_playback_commands,
    web_status_for_playback,
)
from abs_kids_player.podcast import podcast_book
from abs_kids_player.appliance_io import (
    InputEvent,
    Sh1122Display,
    oled_safe_text,
    scale_grayscale_value,
    screen_saver_word_specs,
)
from abs_kids_player.audio import AudioError, VolumeState
from abs_kids_player.bluetooth_audio import BluetoothActionResult
from abs_kids_player.playback import PlaybackError
from abs_kids_player.player_control import load_web_player_status, queue_web_player_command
from abs_kids_player.rotary_ui import (
    ApplianceMenu,
    BluetoothDevicesFrame,
    BluetoothMenuFrame,
    MenuCommand,
    CommandType,
    HomeFrame,
    PlayingFrame,
    ResumeChoiceFrame,
    ScreenSaverFrame,
    SplashFrame,
    TwoLineFrame,
    VolumeFrame,
    WifiSetupFrame,
)
from abs_kids_player.wifi import SETUP_HOTSPOT_SSID, SETUP_HOTSPOT_URL, WifiStatus


class FakeClient:
    def __init__(self, _server_url: str, _token: str) -> None:
        pass

    def choose_library_id(self, configured_id: str = "") -> str:
        return configured_id or "library-1"

    def get_books(self, _library_id: str) -> list[Book]:
        return [Book(id="book-1", title="The Hobbit", author="J.R.R. Tolkien", duration=1, cover_url="")]


class FakeFailingClient:
    def __init__(self, _server_url: str, _token: str) -> None:
        pass

    def choose_library_id(self, _configured_id: str = "") -> str:
        raise AudiobookshelfError("server unavailable")


def make_podcast_config() -> PodcastConfig:
    return PodcastConfig(
        url="https://podcasts.apple.com/us/podcast/story-show/id123",
        title="Story Show",
        author="Story Parent",
        feed_url="https://feeds.example.com/story.xml",
        book_id="podcast:apple:123",
    )


class FakeAmpShutdown:
    def __init__(self) -> None:
        self.states: list[bool] = []

    def set_shutdown(self, shutdown: bool) -> None:
        self.states.append(shutdown)


class FakePlayback:
    def __init__(self, session: PlaybackSession | None = None) -> None:
        self.session = session
        self.current_time = 0.0
        self.is_playing = False
        self.seek_times: list[float] = []
        self.resume_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0
        self.audio_refresh_calls = 0
        self.volume_states: list[tuple[int, bool]] = []

    def start(self, _session, _client) -> None:
        raise AssertionError("Existing active sessions should not be restarted.")

    def seek_global(self, seek_time: float) -> None:
        self.current_time = seek_time
        self.seek_times.append(seek_time)

    def resume(self, sync: bool = False, percent: int | None = None, muted: bool | None = None) -> None:
        self.is_playing = True
        self.resume_calls += 1
        if percent is not None and muted is not None:
            self.volume_states.append((percent, muted))

    def pause(self, sync: bool = True) -> None:
        self.is_playing = False
        self.pause_calls += 1

    def stop(self) -> None:
        self.session = None
        self.current_time = 0.0
        self.is_playing = False
        self.stop_calls += 1

    def refresh_audio_output(self) -> None:
        self.audio_refresh_calls += 1

    def set_volume_state(self, percent: int, muted: bool) -> None:
        self.volume_states.append((percent, muted))


class FakePollingErrorPlayback:
    def poll(self) -> None:
        raise PlaybackError("GStreamer playback error.")


class FakeStartingPlayback:
    def __init__(self) -> None:
        self.session = None
        self.current_time = 0.0
        self.is_playing = False
        self.started_sessions: list[PlaybackSession] = []

    def start(self, session, _client) -> None:
        self.session = session
        self.current_time = session.current_time
        self.is_playing = True
        self.started_sessions.append(session)


class FakePlaybackClient:
    def __init__(self, _server_url: str, _token: str) -> None:
        pass

    def start_playback(self, _book_id: str, start_over: bool = False, resume_time: float = 0) -> PlaybackSession:
        session = make_playback_session()
        session.current_time = 0 if start_over else resume_time
        return session


def make_playback_session() -> PlaybackSession:
    return PlaybackSession(
        id="session-1",
        library_item_id="book-1",
        title="The Hobbit",
        author="J.R.R. Tolkien",
        duration=300,
        current_time=60,
        cover_url="",
        tracks=[AudioTrack(1, 0, 300, "http://example.test/book.mp3", "Track")],
        chapters=[
            Chapter(1, "An Unexpected Party", 0, 120),
            Chapter(2, "Roast Mutton", 120, 300),
        ],
    )


class OledServiceTest(unittest.TestCase):
    def test_home_jump_letter_uses_its_own_larger_font_without_moving_content(self) -> None:
        display = object.__new__(Sh1122Display)
        display.draw = Mock()
        display.font_home_title = object()
        display.font_home_author = object()
        display.font_section_letter = object()
        display.draw_centered_text = Mock()
        display.draw_scrolling_text = Mock()
        display.draw_bottom_left_text = Mock()
        display.draw_bottom_right_text = Mock()

        with (
            patch("abs_kids_player.appliance_io.text_width", return_value=20),
            patch("abs_kids_player.appliance_io.fit_text", side_effect=lambda _draw, text, _font, _width: text),
        ):
            display.draw_home(HomeFrame("Matilda", "By Roald Dahl", section_letter="M", section_letter_fill=200))

        self.assertEqual(display.draw_centered_text.call_args_list[0].kwargs["y"], 12)
        self.assertEqual(display.draw_centered_text.call_args_list[1].kwargs["y"], 34)
        display.draw_bottom_right_text.assert_called_once_with(
            "M",
            display.font_section_letter,
            fill=200,
            margin=3,
        )

    def test_oled_text_uses_ascii_apostrophes(self) -> None:
        self.assertEqual(oled_safe_text("Charlotte\u2019s Web"), "Charlotte's Web")
        self.assertEqual(oled_safe_text("Dragon\ufffds Promise"), "Dragon's Promise")

    def test_oled_text_normalizes_other_typographic_punctuation(self) -> None:
        self.assertEqual(
            oled_safe_text("\u201cHello\u201d\u00a0\u2014 wait\u2026"),
            '"Hello" - wait...',
        )

    def test_splash_frame_says_chapter(self) -> None:
        frame = splash_frame()

        self.assertIsInstance(frame, SplashFrame)
        self.assertEqual(frame.text, "chapter")

    def test_software_update_frame_warns_against_powering_off(self) -> None:
        self.assertEqual(SOFTWARE_UPDATE_FRAME.top, "UPDATING")
        self.assertEqual(SOFTWARE_UPDATE_FRAME.bottom, "DO NOT POWER OFF")

    def test_update_mode_discards_rotary_events(self) -> None:
        events: queue.SimpleQueue[InputEvent] = queue.SimpleQueue()
        events.put(InputEvent("nav", 1))
        events.put(InputEvent("volume_click"))

        drain_input_events(events)

        self.assertTrue(events.empty())

    def test_signal_boot_splash_handoff_writes_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff"
            with patch("abs_kids_player.oled_service.time.sleep") as sleep:
                signal_boot_splash_handoff(str(path), settle_seconds=0.2)

            self.assertEqual(path.read_text(encoding="utf-8"), "starting\n")
            sleep.assert_called_once_with(0.2)

    def test_setup_hotspot_shows_setup_instructions(self) -> None:
        frame = frame_for_wifi_status(WifiStatus(connected=True, ssid=SETUP_HOTSPOT_SSID))

        self.assertIsInstance(frame, WifiSetupFrame)
        self.assertEqual(frame.ssid, SETUP_HOTSPOT_SSID)
        self.assertEqual(frame.url, SETUP_HOTSPOT_URL)

    def test_home_wifi_shows_setup_address(self) -> None:
        frame = frame_for_wifi_status(WifiStatus(connected=True, ssid="Home WiFi"), lan_ip="192.168.1.42")

        self.assertIsInstance(frame, TwoLineFrame)
        self.assertEqual(frame.top, "Setup address")
        self.assertEqual(frame.bottom, "http://192.168.1.42")

    def test_disconnected_shows_setup_instructions(self) -> None:
        frame = frame_for_wifi_status(WifiStatus(connected=False, message="Not connected"))

        self.assertIsInstance(frame, WifiSetupFrame)
        self.assertEqual(frame.ssid, SETUP_HOTSPOT_SSID)

    def test_boot_state_uses_home_frame_on_home_wifi(self) -> None:
        home = TwoLineFrame("The Hobbit", "By J.R.R. Tolkien")

        frame = frame_for_boot_state(WifiStatus(connected=True, ssid="Home WiFi"), home)

        self.assertEqual(frame, home)

    def test_boot_state_keeps_splash_while_network_is_starting(self) -> None:
        frame = frame_for_boot_state(
            WifiStatus(connected=False, message="NetworkManager starting"),
            startup_waiting=True,
        )

        self.assertIsInstance(frame, SplashFrame)
        self.assertEqual(frame.text, "chapter")

    def test_boot_state_shows_setup_after_network_grace_expires(self) -> None:
        frame = frame_for_boot_state(
            WifiStatus(connected=False, message="Not connected"),
            startup_waiting=False,
        )

        self.assertIsInstance(frame, WifiSetupFrame)

    def test_boot_state_shows_active_setup_hotspot_during_network_grace(self) -> None:
        frame = frame_for_boot_state(
            WifiStatus(connected=True, ssid=SETUP_HOTSPOT_SSID),
            startup_waiting=True,
        )

        self.assertIsInstance(frame, WifiSetupFrame)

    def test_home_frame_for_books_uses_library_home_screen(self) -> None:
        frame = home_frame_for_books(
            [Book(id="book-1", title="The Hobbit", author="J.R.R. Tolkien", duration=1, cover_url="")]
        )

        self.assertIsInstance(frame, HomeFrame)
        self.assertEqual(frame.top, "The Hobbit")
        self.assertEqual(frame.bottom, "By J.R.R. Tolkien")

    def test_load_home_frame_loads_books_from_configured_audiobookshelf(self) -> None:
        frame = load_home_frame(
            AppConfig(server_url="https://books.example.com", token="token", library_id="library-1"),
            client_factory=FakeClient,
        )

        self.assertEqual(frame.top, "The Hobbit")
        self.assertEqual(frame.bottom, "By J.R.R. Tolkien")

    def test_load_home_frame_without_login_shows_setup_address(self) -> None:
        frame = load_home_frame(AppConfig(), lan_ip="192.168.1.42")

        self.assertEqual(frame.top, "Setup address")
        self.assertEqual(frame.bottom, "http://192.168.1.42")

    def test_book_load_result_returns_books_for_configured_audiobookshelf(self) -> None:
        result = book_load_result(
            AppConfig(server_url="https://books.example.com", token="token", library_id="library-1"),
            client_factory=FakeClient,
        )

        self.assertIsInstance(result, BookLoadResult)
        self.assertIsNotNone(result.books)
        self.assertEqual([book.title for book in result.books], ["The Hobbit"])
        self.assertIsNone(result.error_frame)

    def test_load_library_books_adds_configured_podcast_menu_item(self) -> None:
        podcast = make_podcast_config()
        books = load_library_books(
            AppConfig(
                server_url="https://books.example.com",
                token="token",
                library_id="library-1",
                podcasts=[podcast],
            ),
            client_factory=FakeClient,
        )

        self.assertEqual(books[-1], podcast_book(podcast))

    def test_sorted_books_for_menu_merges_podcasts_with_audiobooks(self) -> None:
        books = sorted_books_for_menu(
            [
                Book(id="book-1", title="The Hobbit", author="J.R.R. Tolkien", duration=1, cover_url=""),
                Book(id="podcast:yoto-daily", title="Yoto Daily", author="Yoto", duration=0, cover_url=""),
                Book(id="book-2", title="A Bear Called Paddington", author="Michael Bond", duration=1, cover_url=""),
                Book(id="podcast:trivia-for-kids", title="Trivia for Kids", author="KRCreative", duration=0, cover_url=""),
            ]
        )

        self.assertEqual([book.title for book in books], [
            "A Bear Called Paddington",
            "The Hobbit",
            "Trivia for Kids",
            "Yoto Daily",
        ])

    def test_sorted_books_for_menu_uses_series_title(self) -> None:
        books = sorted_books_for_menu(
            [
                Book(id="book-2", title="Book Two", author="Author", duration=1, cover_url="", series_name="Zebra Tales"),
                Book(id="book-1", title="Matilda", author="Roald Dahl", duration=1, cover_url=""),
            ]
        )

        self.assertEqual([book.display_title for book in books], ["Matilda", "Zebra Tales: Book Two"])

    def test_sorted_books_for_menu_can_order_by_author_last_name(self) -> None:
        books = sorted_books_for_menu(
            [
                Book(id="book-1", title="The Hobbit", author="J.R.R. Tolkien", duration=1, cover_url=""),
                Book(id="book-2", title="Matilda", author="Roald Dahl", duration=1, cover_url=""),
                Book(id="book-3", title="A Bear Called Paddington", author="Michael Bond", duration=1, cover_url=""),
                Book(id="book-4", title="Mystery Book", author="", duration=1, cover_url=""),
            ],
            LIBRARY_SORT_AUTHOR,
        )

        self.assertEqual(
            [book.title for book in books],
            ["A Bear Called Paddington", "Matilda", "The Hobbit", "Mystery Book"],
        )

    def test_book_load_result_turns_audiobookshelf_error_into_display_frame(self) -> None:
        result = book_load_result(
            AppConfig(server_url="https://books.example.com", token="token", library_id="library-1"),
            client_factory=FakeFailingClient,
        )

        self.assertIsNone(result.books)
        self.assertIsInstance(result.error_frame, TwoLineFrame)
        self.assertEqual(result.error_frame.top, "Books unavailable")

    def test_start_book_load_worker_queues_book_result(self) -> None:
        results: queue.SimpleQueue[BookLoadResult] = queue.SimpleQueue()

        start_book_load_worker(
            AppConfig(server_url="https://books.example.com", token="token", library_id="library-1"),
            results,
            client_factory=FakeClient,
        )
        result = results.get(timeout=1)

        self.assertIsNotNone(result.books)
        self.assertEqual(result.books[0].title, "The Hobbit")

    def test_save_playback_state_persists_active_session(self) -> None:
        playback = FakePlayback(make_playback_session())
        playback.current_time = 88

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_STATE_PATH": str(path)}):
                saved = save_playback_state(playback)
                state = load_player_state()

        self.assertTrue(saved)
        self.assertIsNotNone(state)
        self.assertEqual(state.book_id, "book-1")
        self.assertEqual(state.title, "The Hobbit")
        self.assertEqual(state.current_time, 88)

    def test_poll_playback_safely_returns_frame_on_playback_error(self) -> None:
        frame = poll_playback_safely(FakePollingErrorPlayback())

        self.assertIsInstance(frame, TwoLineFrame)
        self.assertEqual(frame.top, "Playback stopped")
        self.assertEqual(frame.bottom, "Check audio")

    def test_web_status_for_playback_reports_active_session(self) -> None:
        playback = FakePlayback(make_playback_session())
        playback.current_time = 88
        playback.is_playing = True

        status = web_status_for_playback(playback, volume_percent=55, muted=False)

        self.assertEqual(status.title, "The Hobbit")
        self.assertTrue(status.is_playing)
        self.assertEqual(status.current_time, 88)
        self.assertEqual(status.volume_percent, 55)

    def test_sleep_transition_publishes_paused_player_status(self) -> None:
        session = make_playback_session()
        playback = FakePlayback(session)
        playback.current_time = 88
        playback.is_playing = True
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "")])
        menu.set_session(session, is_playing=True)

        with tempfile.TemporaryDirectory() as directory:
            status_path = str(Path(directory) / "status.json")
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_WEB_STATUS_PATH": status_path}):
                pause_and_publish_playback(playback, menu, volume_percent=55, muted=False)
                status = load_web_player_status()

        self.assertEqual(playback.pause_calls, 1)
        self.assertFalse(playback.is_playing)
        self.assertFalse(menu.is_playing)
        self.assertFalse(status.is_playing)
        self.assertEqual(status.current_time, 88)

    def test_web_player_commands_pause_play_and_adjust_volume(self) -> None:
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "")])
        session = make_playback_session()
        playback = FakePlayback(session)
        playback.current_time = 88
        playback.is_playing = True
        menu.set_session(session, is_playing=True)

        with tempfile.TemporaryDirectory() as directory:
            command_path = str(Path(directory) / "commands.json")
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_WEB_COMMANDS_PATH": command_path}):
                queue_web_player_command("pause")
                volume, muted, changed, refresh_library = handle_web_player_commands(playback, menu, 50, False)

                self.assertTrue(changed)
                self.assertFalse(refresh_library)
                self.assertEqual(playback.pause_calls, 1)
                self.assertFalse(menu.is_playing)
                self.assertEqual((volume, muted), (50, False))

                queue_web_player_command("play")
                queue_web_player_command("volume", 25)
                volume, muted, changed, refresh_library = handle_web_player_commands(playback, menu, volume, muted)

        self.assertTrue(changed)
        self.assertFalse(refresh_library)
        self.assertEqual(playback.resume_calls, 1)
        self.assertTrue(menu.is_playing)
        self.assertEqual((volume, muted), (25, False))
        self.assertEqual(playback.volume_states[-1], (25, False))

    def test_web_refresh_library_command_pauses_stops_and_returns_home(self) -> None:
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "")])
        session = make_playback_session()
        playback = FakePlayback(session)
        playback.current_time = 88
        playback.is_playing = True
        menu.set_session(session, is_playing=True)

        with tempfile.TemporaryDirectory() as directory:
            command_path = str(Path(directory) / "commands.json")
            state_path = str(Path(directory) / "last-playback.json")
            with patch.dict(
                "os.environ",
                {
                    "ABS_KIDS_PLAYER_WEB_COMMANDS_PATH": command_path,
                    "ABS_KIDS_PLAYER_STATE_PATH": state_path,
                },
            ):
                save_last_playback("book-1", "The Hobbit", 88)
                queue_web_player_command("refresh_library")
                volume, muted, changed, refresh_library = handle_web_player_commands(playback, menu, 50, False)

                self.assertTrue(changed)
                self.assertTrue(refresh_library)
                self.assertEqual(playback.pause_calls, 1)
                self.assertEqual(playback.stop_calls, 1)
                self.assertIsNone(playback.session)
                self.assertEqual(menu.screen, "library")
                self.assertFalse(menu.books)
                self.assertIsNone(load_player_state())
                self.assertEqual((volume, muted), (50, False))

    def test_web_resort_library_command_keeps_playback_running(self) -> None:
        menu = ApplianceMenu(
            [
                Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, ""),
                Book("book-2", "Matilda", "Roald Dahl", 300, ""),
            ]
        )
        session = make_playback_session()
        playback = FakePlayback(session)
        playback.is_playing = True
        menu.set_session(session, is_playing=True)

        with tempfile.TemporaryDirectory() as directory:
            command_path = str(Path(directory) / "commands.json")
            with (
                patch.dict("os.environ", {"ABS_KIDS_PLAYER_WEB_COMMANDS_PATH": command_path}),
                patch(
                    "abs_kids_player.oled_service.load_config",
                    return_value=AppConfig(library_sort_mode=LIBRARY_SORT_AUTHOR),
                ),
            ):
                queue_web_player_command("resort_library")
                volume, muted, changed, refresh_library = handle_web_player_commands(
                    playback,
                    menu,
                    50,
                    False,
                )

        self.assertTrue(changed)
        self.assertFalse(refresh_library)
        self.assertEqual([book.title for book in menu.books], ["Matilda", "The Hobbit"])
        self.assertEqual(menu.library_sort_mode, LIBRARY_SORT_AUTHOR)
        self.assertTrue(playback.is_playing)
        self.assertEqual(playback.pause_calls, 0)
        self.assertEqual(playback.stop_calls, 0)
        self.assertEqual((volume, muted), (50, False))

    def test_home_title_does_not_scroll_before_delay(self) -> None:
        frame = HomeFrame("A Very Long Audiobook Title", "Author")

        self.assertEqual(scrolled_home_frame(frame, elapsed_seconds=1.9), frame)

    def test_home_title_scrolls_after_delay(self) -> None:
        frame = scrolled_home_frame(
            HomeFrame(
                "A Very Long Audiobook Title",
                "Author",
                series_position="2/7",
                section_letter="A",
                section_letter_fill=128,
                is_podcast=True,
            ),
            elapsed_seconds=3.0,
        )

        self.assertIsInstance(frame, HomeFrame)
        self.assertTrue(frame.title_scrolling)
        self.assertEqual(frame.title_scroll_px, 16)
        self.assertEqual(frame.section_letter, "A")
        self.assertEqual(frame.section_letter_fill, 128)
        self.assertEqual(frame.series_position, "2/7")
        self.assertTrue(frame.is_podcast)

    def test_home_cache_refresh_keeps_scroll_timer_when_book_is_same(self) -> None:
        old = HomeFrame("A Very Long Audiobook Title", "Author")
        new = HomeFrame("A Very Long Audiobook Title", "Author", section_letter="A", section_letter_fill=128)

        frame, loaded_at = refresh_home_cache(old, new, home_frame_loaded_at=12.0, now=99.0)

        self.assertEqual(frame, new)
        self.assertEqual(loaded_at, 12.0)

    def test_home_cache_refresh_resets_scroll_timer_when_book_changes(self) -> None:
        old = HomeFrame("Old Title", "Author")
        new = HomeFrame("New Title", "Author")

        frame, loaded_at = refresh_home_cache(old, new, home_frame_loaded_at=12.0, now=99.0)

        self.assertEqual(frame, new)
        self.assertEqual(loaded_at, 99.0)

    def test_home_cache_refresh_resets_scroll_timer_when_series_position_changes(self) -> None:
        old = HomeFrame("Book Two", "Author", series_position="2/6")
        new = HomeFrame("Book Two", "Author", series_position="2/7")

        frame, loaded_at = refresh_home_cache(old, new, home_frame_loaded_at=12.0, now=99.0)

        self.assertEqual(frame, new)
        self.assertEqual(loaded_at, 99.0)

    def test_screen_saver_starts_after_five_idle_minutes(self) -> None:
        last_input_at = 100.0

        self.assertFalse(
            screen_saver_is_active(
                now=last_input_at + DEFAULT_SCREEN_SAVER_IDLE_SECONDS - 0.1,
                last_input_at=last_input_at,
                idle_seconds=DEFAULT_SCREEN_SAVER_IDLE_SECONDS,
            )
        )
        self.assertTrue(
            screen_saver_is_active(
                now=last_input_at + DEFAULT_SCREEN_SAVER_IDLE_SECONDS,
                last_input_at=last_input_at,
                idle_seconds=DEFAULT_SCREEN_SAVER_IDLE_SECONDS,
            )
        )

    def test_screen_saver_frame_advances_with_idle_time(self) -> None:
        frame = screen_saver_frame(now=305.5, last_input_at=5.0, frames_per_second=8.0)

        self.assertIsInstance(frame, ScreenSaverFrame)
        self.assertEqual(frame.frame_index, 2404)
        self.assertEqual(frame.mode, "chapter")
        self.assertEqual(frame.words, ("chapter",))
        self.assertEqual(frame.brightness_percent, DEFAULT_SCREEN_SAVER_DIM_PERCENT)

    def test_screen_saver_frame_uses_configured_dim_level(self) -> None:
        frame = screen_saver_frame(
            now=305.5,
            last_input_at=5.0,
            brightness_percent=10,
        )

        self.assertEqual(frame.brightness_percent, 10)

    def test_screen_saver_frame_can_use_book_titles(self) -> None:
        frame = screen_saver_frame(
            now=305.5,
            last_input_at=5.0,
            frames_per_second=8.0,
            mode=SCREEN_SAVER_BOOKS,
            words=("Matilda", "The Hobbit"),
        )

        self.assertEqual(frame.mode, SCREEN_SAVER_BOOKS)
        self.assertEqual(frame.words, ("Matilda", "The Hobbit"))

    def test_screen_saver_frame_can_use_clock(self) -> None:
        frame = screen_saver_frame(
            now=305.5,
            last_input_at=5.0,
            frames_per_second=8.0,
            mode=SCREEN_SAVER_CLOCK,
        )

        self.assertEqual(frame.mode, SCREEN_SAVER_CLOCK)
        self.assertRegex(frame.clock_text, r"^\d{1,2}:\d{2} [AP]M$")

    def test_screen_saver_words_for_books_uses_library_titles(self) -> None:
        books = [
            Book(id="book-1", title="The Hobbit", author="J.R.R. Tolkien", duration=1, cover_url=""),
            Book(
                id="book-2",
                title="The Wild Robot Escapes",
                author="Peter Brown",
                duration=1,
                cover_url="",
                series_name="The Wild Robot",
            ),
        ]

        self.assertEqual(
            screen_saver_words_for_mode(SCREEN_SAVER_BOOKS, books),
            ("The Hobbit", "The Wild Robot: The Wild Robot Escapes"),
        )
        self.assertEqual(screen_saver_words_for_mode(SCREEN_SAVER_BOOKS, []), ("chapter",))

    def test_clock_screen_saver_text_uses_am_pm(self) -> None:
        from datetime import datetime

        self.assertEqual(clock_screen_saver_text(datetime(2026, 6, 9, 7, 5)), "7:05 AM")
        self.assertEqual(clock_screen_saver_text(datetime(2026, 6, 9, 19, 5)), "7:05 PM")

    def test_screen_saver_word_specs_move_chapter_words(self) -> None:
        first = screen_saver_word_specs(frame_index=10, width=256, height=64)
        second = screen_saver_word_specs(frame_index=11, width=256, height=64)

        self.assertEqual(len(first), 8)
        self.assertEqual(first[0]["font_index"], 0)
        self.assertNotEqual(first[0]["x"], second[0]["x"])
        self.assertGreater(second[0]["x"], first[0]["x"])
        self.assertGreater(second[1]["x"], first[1]["x"])
        self.assertNotEqual(
            first[0]["font_index"],
            screen_saver_word_specs(frame_index=106, width=256, height=64)[0]["font_index"],
        )

    def test_screen_saver_is_disabled_with_zero_idle_seconds(self) -> None:
        self.assertFalse(screen_saver_is_active(now=999.0, last_input_at=0.0, idle_seconds=0.0))

    def test_listening_sleep_timer_counts_only_active_playback(self) -> None:
        timer = ListeningSleepTimer()

        self.assertEqual(timer.update(30, 30, True, 1, "session-1", True), "")
        self.assertEqual(timer.update(50, 20, True, 1, "session-1", False), "")
        self.assertEqual(timer.listened_seconds, 30)
        self.assertEqual(timer.update(80, 30, True, 1, "session-1", True), "prompt")
        self.assertEqual(timer.countdown_seconds(80), 30)

    def test_listening_sleep_timer_counts_down_then_sleeps(self) -> None:
        timer = ListeningSleepTimer()
        timer.update(60, 60, True, 1, "session-1", True)

        self.assertEqual(timer.update(89.1, 0, True, 1, "session-1", False), "")
        self.assertEqual(timer.countdown_seconds(89.1), 1)
        self.assertEqual(timer.update(90, 0, True, 1, "session-1", False), "sleep")
        self.assertTrue(timer.sleeping)
        self.assertEqual(timer.sleep_started_at, 90)

    def test_listening_sleep_timer_confirm_and_wake_reset_interval(self) -> None:
        timer = ListeningSleepTimer()
        timer.update(60, 60, True, 1, "session-1", True)
        timer.confirm()

        self.assertFalse(timer.prompt_active)
        self.assertEqual(timer.listened_seconds, 0)

        timer.update(120, 60, True, 1, "session-1", True)
        timer.update(150, 0, True, 1, "session-1", False)
        self.assertTrue(timer.wake())
        self.assertFalse(timer.sleeping)
        self.assertEqual(timer.listened_seconds, 0)

    def test_disabling_active_sleep_timer_cancels_prompt(self) -> None:
        timer = ListeningSleepTimer()
        timer.update(60, 60, True, 1, "session-1", True)

        event = timer.update(61, 1, False, 1, "session-1", False)

        self.assertEqual(event, "cancel")
        self.assertFalse(timer.prompt_active)
        self.assertFalse(timer.sleeping)

    def test_still_listening_confirmation_resumes_playback(self) -> None:
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "")])
        session = make_playback_session()
        menu.set_session(session, is_playing=False)
        menu.show_sleep_confirmation(30)
        playback = FakePlayback(session)

        overlay = handle_menu_command(
            MenuCommand(CommandType.CONFIRM_STILL_LISTENING),
            menu,
            playback,
        )

        self.assertIsNone(overlay)
        self.assertEqual(playback.resume_calls, 1)
        self.assertTrue(playback.is_playing)
        self.assertTrue(menu.is_playing)

    def test_screen_saver_grayscale_is_scaled_to_selected_percent(self) -> None:
        self.assertEqual(scale_grayscale_value(255, 10), 26)
        self.assertEqual(scale_grayscale_value(180, 10), 18)
        self.assertEqual(scale_grayscale_value(0, 10), 0)

    def test_sh1122_brightness_uses_perceptual_contrast_curve(self) -> None:
        display = object.__new__(Sh1122Display)
        commands: list[list[int]] = []
        display.command = commands.append

        display.set_brightness(25)
        display.set_brightness(50)
        display.set_brightness(100)

        self.assertEqual(commands, [[0x81, 0x06], [0x81, 0x1C], [0x81, 0x80]])

    def test_input_activity_seen_wakes_screen_saver(self) -> None:
        self.assertFalse(input_activity_seen(None, False, [], False))
        self.assertTrue(input_activity_seen(VolumeFrame(50), False, [], False))
        self.assertTrue(input_activity_seen(None, True, [], False))
        self.assertTrue(input_activity_seen(None, False, [MenuCommand(CommandType.HOME)], False))
        self.assertTrue(input_activity_seen(None, False, [], True))

    def test_screen_saver_wake_consumes_all_pending_input(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("nav_click"))
        events.put(InputEvent("nav", steps=1))

        woke, quiet_until = consume_screen_saver_wake_input(
            events,
            screen_saver_visible=True,
            now=100.0,
            quiet_until=0.0,
        )

        self.assertTrue(woke)
        self.assertAlmostEqual(quiet_until, 100.35)
        self.assertTrue(events.empty())

    def test_screen_saver_wake_quiet_period_absorbs_residual_events(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=1))

        woke, quiet_until = consume_screen_saver_wake_input(
            events,
            screen_saver_visible=False,
            now=100.2,
            quiet_until=100.35,
        )

        self.assertFalse(woke)
        self.assertAlmostEqual(quiet_until, 100.55)
        self.assertTrue(events.empty())

    def test_active_screen_does_not_consume_input(self) -> None:
        events = queue.SimpleQueue()
        event = InputEvent("nav_click")
        events.put(event)

        woke, quiet_until = consume_screen_saver_wake_input(
            events,
            screen_saver_visible=False,
            now=101.0,
            quiet_until=100.35,
        )

        self.assertFalse(woke)
        self.assertEqual(quiet_until, 100.35)
        self.assertEqual(events.get_nowait(), event)

    def test_volume_event_falls_back_to_software_volume_when_audio_control_fails(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=1))

        with patch("abs_kids_player.oled_service.change_volume", side_effect=AudioError("missing audio")):
            frame, percent, muted = handle_input_events_with_fallback(
                events,
                fallback_percent=50,
                fallback_muted=False,
            )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(frame.percent, 55)
        self.assertEqual(percent, 55)
        self.assertFalse(muted)

    def test_volume_click_fallback_shows_muted_without_zeroing_percent(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume_click"))

        with patch("abs_kids_player.oled_service.toggle_mute", side_effect=AudioError("missing audio")):
            frame, percent, muted = handle_input_events_with_fallback(
                events,
                fallback_percent=50,
                fallback_muted=False,
            )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(frame.percent, 50)
        self.assertEqual(frame.top, "Muted")
        self.assertTrue(frame.is_muted)
        self.assertEqual(percent, 50)
        self.assertTrue(muted)

    def test_mute_indicator_is_added_to_non_volume_frames_only(self) -> None:
        home = frame_with_mute_indicator(HomeFrame("Matilda", "Roald Dahl"), muted=True)
        volume_frame = VolumeFrame(50, muted=True)
        volume = frame_with_mute_indicator(volume_frame, muted=True)

        self.assertIsInstance(home, HomeFrame)
        self.assertTrue(home.muted)
        self.assertIs(volume, volume_frame)

    def test_status_indicator_adds_bluetooth_connection_to_frames(self) -> None:
        frame = frame_with_status_indicators(HomeFrame("Matilda", "Roald Dahl"), muted=False, bluetooth_connected=True)

        self.assertIsInstance(frame, HomeFrame)
        self.assertTrue(frame.bluetooth_connected)
        self.assertFalse(frame.muted)

    def test_bluetooth_success_frame_says_paired_successfully(self) -> None:
        frame = bluetooth_result_frame(
            BluetoothActionResult(True, "Bluetooth connected", enabled=True, device_name="Playroom Speaker")
        )

        self.assertEqual(frame.top, "Paired Successfully!")
        self.assertEqual(frame.bottom, "Playroom Speaker")

    def test_bluetooth_unpair_frame_returns_to_internal_speaker(self) -> None:
        frame = bluetooth_result_frame(
            BluetoothActionResult(
                True,
                "Bluetooth unpaired",
                enabled=True,
                connected=False,
                device_name="Playroom Speaker",
            )
        )

        self.assertEqual(frame.top, "Bluetooth unpaired")
        self.assertEqual(frame.bottom, "Internal speaker")

    def test_amp_shutdown_tracks_muted_or_zero_volume(self) -> None:
        amp = FakeAmpShutdown()

        self.assertTrue(set_amp_shutdown(amp, muted=True, volume_percent=50))
        self.assertTrue(set_amp_shutdown(amp, muted=False, volume_percent=0))
        self.assertFalse(set_amp_shutdown(amp, muted=False, volume_percent=50))

        self.assertEqual(amp.states, [True, True, False])

    def test_muted_play_command_unmutes_and_consumes_toggle(self) -> None:
        command = MenuCommand(CommandType.TOGGLE_PLAYBACK)

        commands, percent, muted, unmuted, resume = unmute_for_audible_playback_commands(
            [command],
            fallback_percent=50,
            fallback_muted=True,
            software_volume_only=True,
        )

        self.assertEqual(commands, [])
        self.assertEqual(percent, 50)
        self.assertFalse(muted)
        self.assertTrue(unmuted)
        self.assertTrue(resume)

    def test_muted_play_book_command_unmutes_but_still_starts_book(self) -> None:
        command = MenuCommand(CommandType.PLAY_BOOK, book_id="book-1")

        commands, percent, muted, unmuted, resume = unmute_for_audible_playback_commands(
            [command],
            fallback_percent=0,
            fallback_muted=False,
            software_volume_only=True,
        )

        self.assertEqual(commands, [command])
        self.assertEqual(percent, DEFAULT_UNMUTE_VOLUME_PERCENT)
        self.assertFalse(muted)
        self.assertTrue(unmuted)
        self.assertFalse(resume)

    def test_continue_current_book_returns_to_active_session_without_restart(self) -> None:
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "", current_time=60, progress=0.2)])
        playback = FakePlayback(make_playback_session())
        playback.current_time = 137
        playback.is_playing = True

        overlay = handle_menu_command(
            MenuCommand(CommandType.PLAY_BOOK, book_id="book-1", start_over=False, resume_time=60),
            menu,
            playback,
        )

        self.assertIsNone(overlay)
        frame = menu.render()
        self.assertIsInstance(frame, PlayingFrame)
        self.assertEqual(frame.chapter_text, "Roast Mutton")
        self.assertEqual(frame.remaining_text, "-2:43")

    def test_continue_current_book_fetches_history_when_not_playing(self) -> None:
        playback = FakePlayback(make_playback_session())
        playback.current_time = 137
        playback.is_playing = False

        self.assertFalse(
            should_return_to_active_session(
                MenuCommand(CommandType.PLAY_BOOK, book_id="book-1", start_over=False, resume_time=60),
                playback,
            )
        )

    def test_pause_playback_command_pauses_active_playback(self) -> None:
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "")])
        session = make_playback_session()
        menu.set_session(session, is_playing=True)
        playback = FakePlayback(session)
        playback.current_time = 137
        playback.is_playing = True

        overlay = handle_menu_command(MenuCommand(CommandType.PAUSE_PLAYBACK), menu, playback)

        self.assertIsNone(overlay)
        self.assertEqual(playback.pause_calls, 1)
        self.assertFalse(menu.is_playing)

    def test_confirmed_chapter_seek_resumes_when_paused(self) -> None:
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "")])
        session = make_playback_session()
        menu.set_session(session, is_playing=False)
        playback = FakePlayback(session)
        playback.current_time = 60
        playback.is_playing = False

        overlay = handle_menu_command(
            MenuCommand(CommandType.SEEK_CHAPTER, chapter_index=1, seek_time=120),
            menu,
            playback,
        )

        self.assertIsNone(overlay)
        self.assertEqual(playback.seek_times, [120])
        self.assertEqual(playback.resume_calls, 1)
        self.assertTrue(menu.is_playing)

    def test_clear_last_playback_command_removes_saved_state(self) -> None:
        menu = ApplianceMenu()
        playback = FakePlayback()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_STATE_PATH": str(path)}):
                save_last_playback("book-1", "The Hobbit", 10)
                overlay = handle_menu_command(
                    MenuCommand(CommandType.CLEAR_LAST_PLAYBACK),
                    menu,
                    playback,
                )

                state = load_player_state()

        self.assertIsNone(overlay)
        self.assertIsNone(state)

    def test_play_book_command_with_result_queue_returns_loading_frame_immediately(self) -> None:
        menu = ApplianceMenu([Book("book-1", "The Hobbit", "J.R.R. Tolkien", 300, "", current_time=60, progress=0.2)])
        playback = FakeStartingPlayback()
        results: queue.SimpleQueue = queue.SimpleQueue()

        with patch("abs_kids_player.oled_service.load_config", return_value=AppConfig("https://books.example.com", "token")):
            with patch("abs_kids_player.oled_service.AudiobookshelfClient", FakePlaybackClient):
                overlay = handle_menu_command(
                    MenuCommand(CommandType.PLAY_BOOK, book_id="book-1", start_over=False, resume_time=60),
                    menu,
                    playback,
                    results,
                )

                result = results.get(timeout=1)

        self.assertEqual(overlay, BOOK_LOADING_FRAME)
        self.assertEqual(result.session.current_time, 60)
        self.assertEqual(len(playback.started_sessions), 1)

    def test_configured_podcast_command_starts_latest_podcast_episode(self) -> None:
        podcast = make_podcast_config()
        menu = ApplianceMenu([podcast_book(podcast)])
        playback = FakeStartingPlayback()
        results: queue.SimpleQueue = queue.SimpleQueue()
        session = PlaybackSession(
            id="episode-1",
            library_item_id=podcast.book_id,
            title=podcast.title,
            author=podcast.author,
            duration=1013,
            current_time=0,
            cover_url="",
            tracks=[AudioTrack(1, 0, 1013, "https://example.com/story.mp3", "Draw-Along with Jake")],
            chapters=[Chapter(1, "Draw-Along with Jake", 0, 1013)],
        )

        with (
            patch("abs_kids_player.oled_service.load_config", return_value=AppConfig(podcasts=[podcast])),
            patch("abs_kids_player.oled_service.latest_podcast_session", return_value=session) as latest_session,
        ):
            overlay = handle_menu_command(
                MenuCommand(CommandType.PLAY_BOOK, book_id=podcast.book_id, start_over=True),
                menu,
                playback,
                results,
            )
            result = results.get(timeout=1)

        self.assertEqual(overlay, BOOK_LOADING_FRAME)
        latest_session.assert_called_once_with(podcast, resume_time=0, start_over=True)
        self.assertEqual(result.session, session)
        self.assertEqual(playback.started_sessions, [session])

    def test_nav_event_moves_selected_book(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("nav", steps=1))
        clicks = []
        spoken = []
        menu = ApplianceMenu(
            [
                Book(id="book-1", title="The Hobbit", author="J.R.R. Tolkien", duration=1, cover_url=""),
                Book(id="book-2", title="Matilda", author="Roald Dahl", duration=1, cover_url=""),
            ]
        )

        _frame, _percent, _muted, changed, commands, pause_playback, resume_playback = handle_oled_input_events(
            events,
            menu,
            control_click_feedback=lambda: clicks.append("click"),
            spoken_navigation_feedback=spoken.append,
        )

        self.assertTrue(changed)
        self.assertEqual(clicks, ["click"])
        self.assertEqual(commands, [])
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)
        self.assertEqual(menu.render().top, "Matilda")
        self.assertEqual(spoken[0].text, "Matilda")
        self.assertGreater(spoken[0].delay_seconds, 0)

    def test_nav_click_opens_resume_choice_when_book_has_history(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("nav_click"))
        clicks = []
        spoken = []
        speech_cancels = []
        menu = ApplianceMenu(
            [
                Book(
                    id="book-1",
                    title="The Hobbit",
                    author="J.R.R. Tolkien",
                    duration=1,
                    cover_url="",
                    current_time=30,
                    progress=0.1,
                )
            ]
        )

        _frame, _percent, _muted, changed, commands, pause_playback, resume_playback = handle_oled_input_events(
            events,
            menu,
            control_click_feedback=lambda: clicks.append("click"),
            spoken_navigation_feedback=spoken.append,
            spoken_navigation_cancel=lambda: speech_cancels.append("cancel"),
        )

        self.assertTrue(changed)
        self.assertEqual(clicks, ["click"])
        self.assertEqual(commands, [])
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)
        frame = menu.render()
        self.assertIsInstance(frame, ResumeChoiceFrame)
        self.assertEqual(frame.top, "The Hobbit")
        self.assertEqual(frame.options, ("Home", "Continue", "Start over"))
        self.assertEqual(frame.selected_index, 1)
        self.assertEqual(spoken[0].text, "Continue")
        self.assertEqual(spoken[0].delay_seconds, 0)
        self.assertEqual(speech_cancels, ["cancel"])

    def test_nav_click_without_history_opens_home_start_choice(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("nav_click"))
        menu = ApplianceMenu(
            [Book(id="book-1", title="The Hobbit", author="J.R.R. Tolkien", duration=1, cover_url="")]
        )

        frame, _percent, _muted, changed, commands, pause_playback, resume_playback = handle_oled_input_events(
            events, menu
        )

        self.assertTrue(changed)
        self.assertIsNone(frame)
        self.assertEqual(commands, [])
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)
        rendered = menu.render()
        self.assertIsInstance(rendered, ResumeChoiceFrame)
        self.assertEqual(rendered.top, "The Hobbit")
        self.assertEqual(rendered.options, ("Home", "Start"))
        self.assertEqual(rendered.selected_index, 1)

    def test_nav_hold_opens_bluetooth_menu(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("nav_hold"))
        menu = ApplianceMenu()

        frame, _percent, _muted, changed, commands, pause_playback, resume_playback = handle_oled_input_events(
            events,
            menu,
            bluetooth_enabled=False,
        )

        self.assertIsNone(frame)
        self.assertTrue(changed)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].type, CommandType.PAUSE_PLAYBACK)
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)
        rendered = menu.render()
        self.assertIsInstance(rendered, BluetoothMenuFrame)
        self.assertFalse(rendered.enabled)
        self.assertEqual(rendered.options, ("Back", "Enable", "Pair"))

    def test_bluetooth_scan_command_starts_worker_and_returns_pairing_frame(self) -> None:
        menu = ApplianceMenu()
        playback = FakePlayback()
        results: queue.SimpleQueue[BluetoothActionResult] = queue.SimpleQueue()

        with patch("abs_kids_player.oled_service.start_bluetooth_scan_worker") as start_worker:
            overlay = handle_menu_command(
                MenuCommand(CommandType.START_BLUETOOTH_SCAN),
                menu,
                playback,
                bluetooth_results=results,
            )

        start_worker.assert_called_once_with(results)
        self.assertEqual(overlay, BLUETOOTH_PAIRING_FRAME)

    def test_bluetooth_pair_device_command_starts_worker_for_selected_device(self) -> None:
        menu = ApplianceMenu()
        playback = FakePlayback()
        results: queue.SimpleQueue[BluetoothActionResult] = queue.SimpleQueue()

        with patch("abs_kids_player.oled_service.start_bluetooth_pairing_worker") as start_worker:
            overlay = handle_menu_command(
                MenuCommand(
                    CommandType.PAIR_BLUETOOTH_DEVICE,
                    bluetooth_device_address="AA:BB:CC:DD:EE:FF",
                    bluetooth_device_name="Playroom Speaker",
                ),
                menu,
                playback,
                bluetooth_results=results,
            )

        self.assertEqual(start_worker.call_args.args[0].address, "AA:BB:CC:DD:EE:FF")
        self.assertIs(start_worker.call_args.args[1], results)
        self.assertEqual(overlay.top, "Pairing")
        self.assertEqual(overlay.bottom, "Playroom Speaker")

    def test_bluetooth_unpair_command_starts_worker(self) -> None:
        menu = ApplianceMenu()
        playback = FakePlayback()
        results: queue.SimpleQueue[BluetoothActionResult] = queue.SimpleQueue()

        with patch("abs_kids_player.oled_service.start_bluetooth_unpair_worker") as start_worker:
            overlay = handle_menu_command(
                MenuCommand(CommandType.UNPAIR_BLUETOOTH_DEVICE),
                menu,
                playback,
                bluetooth_results=results,
            )

        start_worker.assert_called_once_with(results)
        self.assertEqual(overlay.top, "Unpairing")
        self.assertEqual(overlay.bottom, "Bluetooth device")

    def test_scan_result_populates_scrollable_bluetooth_device_list(self) -> None:
        menu = ApplianceMenu()

        menu.set_bluetooth_devices(
            [
                ("AA:BB:CC:DD:EE:FF", "Playroom Speaker"),
                ("11:22:33:44:55:66", "Blue Headphones"),
            ]
        )
        rendered = menu.render()

        self.assertIsInstance(rendered, BluetoothDevicesFrame)
        self.assertEqual(rendered.top, "Bluetooth Devices")
        self.assertEqual(rendered.bottom, "Playroom Speaker 2/3")

    def test_bluetooth_scanning_frame_animates_dots(self) -> None:
        first = bluetooth_scanning_frame(0.0)
        second = bluetooth_scanning_frame(0.5)

        self.assertEqual(first.top, "Put your device in pairing mode")
        self.assertEqual(first.bottom, "Searching.")
        self.assertEqual(second.bottom, "Searching..")

    def test_bluetooth_pairing_frame_animates_dots(self) -> None:
        first = bluetooth_pairing_frame(TwoLineFrame("Pairing", "Playroom Speaker"), 0.0)
        second = bluetooth_pairing_frame(TwoLineFrame("Pairing", "Playroom Speaker"), 0.5)

        self.assertEqual(first.top, "Pairing.")
        self.assertEqual(first.bottom, "Playroom Speaker")
        self.assertEqual(second.top, "Pairing..")

    def test_bluetooth_power_command_starts_worker_and_updates_menu(self) -> None:
        menu = ApplianceMenu()
        playback = FakePlayback()
        results: queue.SimpleQueue[BluetoothActionResult] = queue.SimpleQueue()

        with patch("abs_kids_player.oled_service.start_bluetooth_power_worker") as start_worker:
            overlay = handle_menu_command(
                MenuCommand(CommandType.SET_BLUETOOTH_ENABLED, bluetooth_enabled=False),
                menu,
                playback,
                bluetooth_results=results,
            )

        start_worker.assert_called_once_with(False, results)
        self.assertFalse(menu.bluetooth_enabled)
        self.assertEqual(overlay, BLUETOOTH_POWER_FRAME)

    def test_volume_click_mute_requests_playback_pause(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume_click"))
        menu = ApplianceMenu()

        with patch("abs_kids_player.oled_service.toggle_mute", return_value=VolumeState(percent=50, muted=True)):
            frame, _percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events, menu
            )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(frame.top, "Muted")
        self.assertTrue(muted)
        self.assertTrue(pause_playback)
        self.assertFalse(resume_playback)

    def test_spoken_navigation_announces_volume_at_ten_percent_intervals(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=1))
        events.put(InputEvent("volume", steps=1))
        menu = ApplianceMenu()
        spoken = []

        frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
            events,
            menu,
            fallback_percent=50,
            fallback_muted=False,
            software_volume_only=True,
            spoken_navigation_feedback=spoken.append,
        )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, 60)
        self.assertFalse(muted)
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)
        self.assertEqual([selection.text for selection in spoken], ["Volume 60 percent"])

    def test_spoken_navigation_volume_stops_at_ten_percent(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=-1))
        menu = ApplianceMenu()
        spoken = []

        frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
            events,
            menu,
            fallback_percent=10,
            fallback_muted=False,
            software_volume_only=True,
            spoken_navigation_feedback=spoken.append,
        )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, 10)
        self.assertFalse(muted)
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)
        self.assertEqual(spoken, [])

    def test_spoken_navigation_ignores_volume_knob_mute_click(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume_click"))
        menu = ApplianceMenu()
        spoken = []

        with patch("abs_kids_player.oled_service.toggle_mute") as toggle:
            frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events,
                menu,
                fallback_percent=50,
                fallback_muted=False,
                spoken_navigation_feedback=spoken.append,
            )

        toggle.assert_not_called()
        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, 50)
        self.assertFalse(muted)
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)
        self.assertEqual(spoken, [])

    def test_volume_zero_requests_playback_pause(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=-1))
        menu = ApplianceMenu()

        with patch("abs_kids_player.oled_service.change_volume", return_value=VolumeState(percent=0, muted=False)):
            frame, _percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events, menu
            )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(frame.top, "Muted")
        self.assertFalse(muted)
        self.assertTrue(pause_playback)
        self.assertFalse(resume_playback)

    def test_volume_up_from_zero_requests_playback_resume(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=1))
        menu = ApplianceMenu()

        with patch("abs_kids_player.oled_service.change_volume", side_effect=AudioError("missing audio")):
            frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events,
                menu,
                fallback_percent=0,
                fallback_muted=False,
            )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, 5)
        self.assertFalse(muted)
        self.assertFalse(frame.is_muted)
        self.assertFalse(pause_playback)
        self.assertTrue(resume_playback)

    def test_software_volume_only_skips_system_mixer(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=-1))
        menu = ApplianceMenu()

        with patch("abs_kids_player.oled_service.change_volume") as change:
            frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events,
                menu,
                fallback_percent=50,
                fallback_muted=False,
                software_volume_only=True,
            )

        change.assert_not_called()
        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, 45)
        self.assertFalse(muted)
        self.assertFalse(pause_playback)
        self.assertFalse(resume_playback)

    def test_software_volume_only_zero_requests_pause_without_system_mixer(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume", steps=-1))
        menu = ApplianceMenu()

        with patch("abs_kids_player.oled_service.change_volume") as change:
            frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events,
                menu,
                fallback_percent=5,
                fallback_muted=False,
                software_volume_only=True,
            )

        change.assert_not_called()
        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, 0)
        self.assertFalse(muted)
        self.assertTrue(frame.is_muted)
        self.assertTrue(pause_playback)
        self.assertFalse(resume_playback)

    def test_volume_click_from_zero_restores_volume_and_requests_resume(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume_click"))
        menu = ApplianceMenu()

        with patch("abs_kids_player.oled_service.toggle_mute", side_effect=AudioError("missing audio")):
            frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events,
                menu,
                fallback_percent=0,
                fallback_muted=False,
            )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, DEFAULT_UNMUTE_VOLUME_PERCENT)
        self.assertFalse(muted)
        self.assertFalse(frame.is_muted)
        self.assertFalse(pause_playback)
        self.assertTrue(resume_playback)

    def test_volume_click_unmute_requests_playback_resume(self) -> None:
        events = queue.SimpleQueue()
        events.put(InputEvent("volume_click"))
        menu = ApplianceMenu()

        with patch("abs_kids_player.oled_service.toggle_mute", return_value=VolumeState(percent=50, muted=False)):
            frame, percent, muted, _changed, _commands, pause_playback, resume_playback = handle_oled_input_events(
                events,
                menu,
                fallback_percent=50,
                fallback_muted=True,
            )

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(percent, 50)
        self.assertFalse(muted)
        self.assertFalse(frame.is_muted)
        self.assertFalse(pause_playback)
        self.assertTrue(resume_playback)


if __name__ == "__main__":
    unittest.main()
