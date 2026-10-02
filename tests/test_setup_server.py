from __future__ import annotations

import io
import unittest
from unittest.mock import Mock, patch

from abs_kids_player import __version__
from abs_kids_player.config import (
    LIBRARY_SORT_AUTHOR,
    LIBRARY_SORT_TITLE,
    SCREEN_SAVER_BOOKS,
    SCREEN_SAVER_CLOCK,
    AppConfig,
    PodcastConfig,
)
from abs_kids_player.bluetooth_audio import BluetoothDevice
from abs_kids_player.player_control import WebPlayerStatus
from abs_kids_player.setup_server import (
    PAGE,
    SYSTEM_ACTION_DELAY_SECONDS,
    WIFI_CHANGE_DELAY_SECONDS,
    audiobookshelf_status,
    bluetooth_status,
    login_and_refresh_player,
    login_username,
    player_status_event_signature,
    player_status_payload,
    player_status_sse,
    render_health_page,
    render_podcasts_card,
    render_player_status_value,
    render_system_card,
    render_settings_card,
    render_status_panel,
    render_wifi_card,
    restore_device_defaults,
    schedule_system_reboot,
    schedule_system_reset,
    schedule_wifi_forget,
    save_click_setting,
    save_library_sort_setting,
    save_podcast_settings,
    save_screen_saver_setting,
    save_sleep_timer_setting,
    saved_username,
    SetupHandler,
)
from abs_kids_player.wifi import SETUP_HOTSPOT_SSID, WifiStatus


class FakeAudiobookshelfClient:
    token = "token"
    refresh_token = "refresh-token"

    def __init__(self, _server_url: str, _token: str) -> None:
        pass

    @classmethod
    def login(cls, _server_url: str, _username: str, _password: str):
        return cls(_server_url, cls.token), {"user": {"username": "chapter"}}

    def choose_library_id(self, _library_id: str = "") -> str:
        return "library-1"

    def get_current_user(self) -> dict:
        return {"user": {"username": "chapter"}}


class SetupServerTest(unittest.TestCase):
    def test_health_page_shows_wifi_and_audiobookshelf_success(self) -> None:
        html = render_health_page(
            WifiStatus(connected=True, ssid="Chapter WiFi"),
            (True, "Logged in to https://books.example.com as chapter"),
        )

        self.assertNotIn("Setup Server", html)
        self.assertIn("Connected to <strong>Chapter WiFi</strong>", html)
        self.assertIn("Logged in to <strong>https://books.example.com</strong> as <strong>chapter</strong>", html)
        self.assertIn(f"<strong>v{__version__}</strong>", html)

    def test_health_page_shows_failures(self) -> None:
        html = render_health_page(
            WifiStatus(connected=False, message="Not connected"),
            (False, "Not configured"),
        )

        self.assertIn("Not connected", html)
        self.assertIn("Not configured", html)

    def test_status_panel_shows_same_status_on_main_page(self) -> None:
        html = render_status_panel(
            WifiStatus(connected=True, ssid="Chapter WiFi"),
            (True, "Logged in to https://books.example.com as chapter"),
            WebPlayerStatus(title="The Hobbit", current_time=60, duration=300, is_playing=True, volume_percent=45),
            (True, "Connected to Playroom Speaker"),
        )

        self.assertNotIn("Setup Server", html)
        self.assertIn("Connected to <strong>Chapter WiFi</strong>", html)
        self.assertIn("Logged in to <strong>https://books.example.com</strong> as <strong>chapter</strong>", html)
        self.assertIn("Bluetooth", html)
        self.assertIn("Connected to <strong>Playroom Speaker</strong>", html)
        self.assertNotIn("Software Version", html)
        self.assertIn("Currently Playing", html)
        self.assertIn("The Hobbit", html)
        self.assertIn("data-now-playing-title", html)
        self.assertIn("data-now-playing-meta", html)
        self.assertIn("data-playback-form", html)
        self.assertIn("data-playback-action", html)
        self.assertIn("data-playback-button", html)
        self.assertNotIn("data-live-source", html)
        self.assertIn('name="action" value="pause"', html)
        self.assertNotIn('name="action" value="play"', html)
        self.assertIn('class="volume-icon"', html)
        self.assertIn("&#128266;", html)
        self.assertIn('data-volume-percent>45%</div>', html)
        self.assertIn('data-volume-slider', html)
        self.assertIn('name="volume" type="range"', html)
        self.assertNotIn(">Set</button>", html)

    def test_status_categories_use_full_width_rows(self) -> None:
        self.assertIn("grid-template-columns: 1fr;", PAGE)
        self.assertIn("grid-template-columns: minmax(140px, 180px) minmax(0, 1fr);", PAGE)
        self.assertIn("overflow-wrap: anywhere;", PAGE)

    def test_saved_login_does_not_add_redundant_page_message(self) -> None:
        handler = object.__new__(SetupHandler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()
        config = AppConfig(server_url="https://books.example.com", token="token", username="chapter")

        with (
            patch("abs_kids_player.setup_server.load_config", return_value=config),
            patch(
                "abs_kids_player.setup_server.wifi_status",
                return_value=WifiStatus(connected=True, ssid="Chapter WiFi"),
            ),
            patch(
                "abs_kids_player.setup_server.audiobookshelf_status",
                return_value=(True, "Logged in to https://books.example.com as chapter"),
            ),
            patch("abs_kids_player.setup_server.load_web_player_status", return_value=WebPlayerStatus()),
            patch("abs_kids_player.setup_server.bluetooth_status", return_value=(False, "Not connected")),
        ):
            handler.send_page()

        page = handler.wfile.getvalue().decode("utf-8")
        self.assertNotIn("This player already has an Audiobookshelf login saved.", page)
        self.assertIn("Logged in to <strong>https://books.example.com</strong> as <strong>chapter</strong>", page)

    def test_status_panel_shows_bluetooth_disconnected_by_default(self) -> None:
        html = render_status_panel(
            WifiStatus(connected=True, ssid="Chapter WiFi"),
            (True, "Logged in to https://books.example.com as chapter"),
        )

        self.assertIn("Bluetooth", html)
        self.assertIn("Not connected", html)

    def test_bluetooth_status_reports_connected_device_name(self) -> None:
        with patch(
            "abs_kids_player.setup_server.connected_bluetooth_audio_device",
            return_value=BluetoothDevice("AA:BB:CC:DD:EE:FF", "Playroom Speaker"),
        ):
            self.assertEqual(bluetooth_status(), (True, "Connected to Playroom Speaker"))

    def test_bluetooth_status_reports_not_connected(self) -> None:
        with patch("abs_kids_player.setup_server.connected_bluetooth_audio_device", return_value=None):
            self.assertEqual(bluetooth_status(), (False, "Not connected"))

    def test_player_status_value_shows_nothing_playing_without_session(self) -> None:
        html = render_player_status_value(WebPlayerStatus())

        self.assertIn("Nothing playing", html)
        self.assertIn('data-has-session="0"', html)
        self.assertIn('class="playback-form hidden"', html)
        self.assertIn('class="volume-form hidden"', html)
        self.assertIn('action="/player"', html)

    def test_player_status_value_shows_play_button_when_paused(self) -> None:
        html = render_player_status_value(
            WebPlayerStatus(title="The Hobbit", current_time=60, duration=300, is_playing=False, volume_percent=45)
        )

        self.assertIn('name="action" value="play"', html)
        self.assertIn(">Play</button>", html)
        self.assertNotIn('name="action" value="pause"', html)

    def test_player_status_payload_reports_contextual_button_state(self) -> None:
        payload = player_status_payload(
            WebPlayerStatus(title="The Hobbit", current_time=60, duration=300, is_playing=False, volume_percent=45)
        )

        self.assertTrue(payload["hasSession"])
        self.assertEqual(payload["title"], "The Hobbit")
        self.assertEqual(payload["state"], "Paused")
        self.assertEqual(payload["timeInfo"], "1:00 / 5:00")
        self.assertEqual(payload["currentTime"], 60)
        self.assertEqual(payload["duration"], 300)
        self.assertIn("updatedAt", payload)
        self.assertFalse(payload["isPlaying"])
        self.assertEqual(payload["volumePercent"], 45)

    def test_player_status_sse_formats_status_event(self) -> None:
        event = player_status_sse('{"isPlaying":true}')

        self.assertEqual(event, b'data: {"isPlaying":true}\n\n')

    def test_setup_handler_uses_http11_for_sse(self) -> None:
        from abs_kids_player.setup_server import SetupHandler

        self.assertEqual(SetupHandler.protocol_version, "HTTP/1.1")
        self.assertEqual(SetupHandler.server_version, f"ChapterPlayer/{__version__}")

    def test_player_status_event_signature_ignores_live_time_only(self) -> None:
        paused = player_status_payload(
            WebPlayerStatus(title="The Hobbit", current_time=60, duration=300, is_playing=False, volume_percent=45)
        )
        later = dict(paused)
        later["currentTime"] = 61
        later["updatedAt"] = paused["updatedAt"] + 1
        playing = dict(paused)
        playing["isPlaying"] = True
        playing["state"] = "Playing"

        self.assertEqual(player_status_event_signature(paused), player_status_event_signature(later))
        self.assertNotEqual(player_status_event_signature(paused), player_status_event_signature(playing))

    def test_settings_card_toggles_control_click_sound(self) -> None:
        enabled = render_settings_card(AppConfig(control_click_enabled=True))
        disabled = render_settings_card(AppConfig(control_click_enabled=False))

        self.assertIn("<h2 id=\"settings-heading\">Settings</h2>", enabled)
        self.assertIn('class="settings-list"', enabled)
        self.assertIn('class="settings-row"', enabled)
        self.assertIn('class="setting-name">Control knob click sound</div>', enabled)
        self.assertIn('class="setting-state">Enabled</div>', enabled)
        self.assertIn('class="toggle-button is-on"', enabled)
        self.assertIn('aria-pressed="true"', enabled)
        self.assertIn("Disable control knob click sound", enabled)
        self.assertIn('name="enabled" value="0"', enabled)
        self.assertIn('class="setting-state">Disabled</div>', disabled)
        self.assertIn('class="toggle-button"', disabled)
        self.assertIn('aria-pressed="false"', disabled)
        self.assertIn("Enable control knob click sound", disabled)
        self.assertIn('name="enabled" value="1"', disabled)
        self.assertIn('class="setting-name">Library order</div>', enabled)
        self.assertIn('action="/settings/library-order"', enabled)
        self.assertIn('<option value="title" selected>Title</option>', enabled)

        author_order = render_settings_card(AppConfig(library_sort_mode=LIBRARY_SORT_AUTHOR))
        self.assertIn('class="setting-state">Author (last name)</div>', author_order)
        self.assertIn('<option value="author" selected>Author (last name)</option>', author_order)
        self.assertIn('class="setting-name">Screen saver</div>', enabled)
        self.assertIn('action="/settings/screensaver"', enabled)
        self.assertIn('aria-label="Screen saver dim level"', enabled)
        self.assertIn('<option value="15" selected>15%</option>', enabled)
        self.assertIn('<option value="chapter" selected>Chapter word</option>', enabled)

        clock = render_settings_card(AppConfig(screen_saver_mode=SCREEN_SAVER_CLOCK, screen_saver_dim_percent=10))
        self.assertIn('class="setting-state">Digital clock, 10% dim level</div>', clock)
        self.assertIn('<option value="clock" selected>Digital clock</option>', clock)
        self.assertIn('<option value="10" selected>10% (darkest)</option>', clock)

        sleep_disabled = render_settings_card(AppConfig(sleep_timer_enabled=False, sleep_timer_minutes=45))
        self.assertIn('class="setting-name">Sleep timer</div>', sleep_disabled)
        self.assertIn('class="setting-state">Disabled</div>', sleep_disabled)
        self.assertNotIn('aria-label="Sleep timer minutes"', sleep_disabled)
        self.assertNotIn("minutes of listening", sleep_disabled)

        sleep_enabled = render_settings_card(AppConfig(sleep_timer_enabled=True, sleep_timer_minutes=45))
        self.assertIn('class="setting-name">Sleep timer</div>', sleep_enabled)
        self.assertIn('class="setting-state">Enabled</div>', sleep_enabled)
        self.assertIn('action="/settings/sleep"', sleep_enabled)
        self.assertIn("Ask after", sleep_enabled)
        self.assertIn('aria-label="Sleep timer minutes"', sleep_enabled)
        self.assertIn('value="45"', sleep_enabled)
        self.assertIn("minutes of listening", sleep_enabled)
        self.assertNotIn('class="setting-name">Listening time</div>', sleep_enabled)

    def test_save_click_setting_preserves_login_config(self) -> None:
        podcasts = [PodcastConfig(url="https://podcasts.apple.com/us/podcast/example/id123", title="Example")]
        config = AppConfig(
            server_url="https://books.example.com",
            token="token",
            library_id="library-1",
            username="chapter",
            control_click_enabled=True,
            screen_saver_mode=SCREEN_SAVER_BOOKS,
            podcasts=podcasts,
        )

        with (
            patch("abs_kids_player.setup_server.load_config", return_value=config),
            patch("abs_kids_player.setup_server.save_config") as save_config,
        ):
            updated = save_click_setting(False)

        self.assertEqual(updated.server_url, config.server_url)
        self.assertEqual(updated.token, config.token)
        self.assertEqual(updated.library_id, config.library_id)
        self.assertEqual(updated.username, config.username)
        self.assertFalse(updated.control_click_enabled)
        self.assertEqual(updated.screen_saver_mode, SCREEN_SAVER_BOOKS)
        self.assertEqual(updated.podcasts, podcasts)
        save_config.assert_called_once_with(updated)

    def test_save_library_sort_setting_preserves_config_and_resorts_player(self) -> None:
        config = AppConfig(
            server_url="https://books.example.com",
            token="token",
            username="chapter",
            library_sort_mode=LIBRARY_SORT_TITLE,
        )

        with (
            patch("abs_kids_player.setup_server.load_config", return_value=config),
            patch("abs_kids_player.setup_server.save_config") as save_config,
            patch("abs_kids_player.setup_server.queue_web_player_command") as queue_command,
        ):
            updated = save_library_sort_setting(LIBRARY_SORT_AUTHOR)

        self.assertEqual(updated.library_sort_mode, LIBRARY_SORT_AUTHOR)
        self.assertEqual(updated.server_url, config.server_url)
        self.assertEqual(updated.token, config.token)
        save_config.assert_called_once_with(updated)
        queue_command.assert_called_once_with("resort_library")

    def test_save_screen_saver_setting_preserves_login_config(self) -> None:
        podcasts = [PodcastConfig(url="https://podcasts.apple.com/us/podcast/example/id123", title="Example")]
        config = AppConfig(
            server_url="https://books.example.com",
            token="token",
            library_id="library-1",
            username="chapter",
            control_click_enabled=False,
            screen_saver_dim_percent=25,
            podcasts=podcasts,
        )

        with (
            patch("abs_kids_player.setup_server.load_config", return_value=config),
            patch("abs_kids_player.setup_server.save_config") as save_config,
        ):
            updated = save_screen_saver_setting(SCREEN_SAVER_BOOKS, 10)

        self.assertEqual(updated.server_url, config.server_url)
        self.assertEqual(updated.token, config.token)
        self.assertEqual(updated.library_id, config.library_id)
        self.assertEqual(updated.username, config.username)
        self.assertFalse(updated.control_click_enabled)
        self.assertEqual(updated.screen_saver_mode, SCREEN_SAVER_BOOKS)
        self.assertEqual(updated.screen_saver_dim_percent, 10)
        self.assertEqual(updated.podcasts, podcasts)
        save_config.assert_called_once_with(updated)

    def test_save_sleep_timer_setting_preserves_other_config(self) -> None:
        config = AppConfig(
            server_url="https://books.example.com",
            token="token",
            username="chapter",
            screen_saver_mode=SCREEN_SAVER_BOOKS,
            sleep_timer_enabled=False,
            sleep_timer_minutes=30,
        )

        with (
            patch("abs_kids_player.setup_server.load_config", return_value=config),
            patch("abs_kids_player.setup_server.save_config") as save_config,
        ):
            enabled = save_sleep_timer_setting(enabled=True)
            updated = save_sleep_timer_setting(minutes=45)

        self.assertTrue(enabled.sleep_timer_enabled)
        self.assertEqual(enabled.sleep_timer_minutes, 30)
        self.assertFalse(updated.sleep_timer_enabled)
        self.assertEqual(updated.sleep_timer_minutes, 45)
        self.assertEqual(updated.server_url, config.server_url)
        self.assertEqual(updated.screen_saver_mode, SCREEN_SAVER_BOOKS)
        self.assertEqual(save_config.call_count, 2)

    def test_podcasts_card_shows_saved_podcasts_and_apple_instruction(self) -> None:
        html = render_podcasts_card(
            AppConfig(
                podcasts=[
                    PodcastConfig(
                        url="https://podcasts.apple.com/us/podcast/yoto-daily/id1635154611",
                        title="Yoto Daily",
                        author="Yoto",
                    )
                ]
            )
        )

        self.assertIn("<h2 id=\"podcasts-heading\">Podcasts</h2>", html)
        self.assertIn("Paste the show link from podcasts.apple.com", html)
        self.assertIn('action="/podcasts"', html)
        self.assertIn('name="podcast_url"', html)
        self.assertIn("Yoto Daily by Yoto", html)
        self.assertIn("Add row", html)
        self.assertIn("Save Podcasts", html)

    def test_save_podcast_settings_resolves_urls_preserves_login_and_refreshes_library(self) -> None:
        config = AppConfig(
            server_url="https://books.example.com",
            token="token",
            library_id="library-1",
            username="chapter",
            podcasts=[],
        )
        resolved = PodcastConfig(
            url="https://podcasts.apple.com/us/podcast/example/id123",
            title="Example",
            author="Parent",
            feed_url="https://feeds.example.com/example.xml",
            book_id="podcast:apple:123",
        )

        with (
            patch("abs_kids_player.setup_server.load_config", return_value=config),
            patch("abs_kids_player.setup_server.resolve_podcast_config", return_value=resolved) as resolve_podcast,
            patch("abs_kids_player.setup_server.save_config") as save_config,
            patch("abs_kids_player.setup_server.queue_web_player_command") as queue_command,
        ):
            updated = save_podcast_settings(
                [
                    "",
                    "https://podcasts.apple.com/us/podcast/example/id123",
                    "https://podcasts.apple.com/us/podcast/example/id123",
                ]
            )

        resolve_podcast.assert_called_once_with("https://podcasts.apple.com/us/podcast/example/id123")
        self.assertEqual(updated.server_url, config.server_url)
        self.assertEqual(updated.username, config.username)
        self.assertEqual(updated.podcasts, [resolved])
        save_config.assert_called_once_with(updated)
        queue_command.assert_called_once_with("refresh_library")

    def test_click_setting_post_redirects_home_after_save(self) -> None:
        body = b"enabled=0"
        handler = object.__new__(SetupHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.redirect_home = Mock()

        with patch("abs_kids_player.setup_server.save_click_setting") as save_setting:
            handler.handle_click_setting_post()

        save_setting.assert_called_once_with(False)
        handler.redirect_home.assert_called_once_with()

    def test_library_sort_setting_post_redirects_home_after_save(self) -> None:
        body = b"library_sort_mode=author"
        handler = object.__new__(SetupHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.redirect_home = Mock()

        with patch("abs_kids_player.setup_server.save_library_sort_setting") as save_setting:
            handler.handle_library_sort_setting_post()

        save_setting.assert_called_once_with(LIBRARY_SORT_AUTHOR)
        handler.redirect_home.assert_called_once_with()

    def test_screen_saver_setting_post_redirects_home_after_save(self) -> None:
        body = b"screen_saver_mode=books&screen_saver_dim_percent=10"
        handler = object.__new__(SetupHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.redirect_home = Mock()

        with patch("abs_kids_player.setup_server.save_screen_saver_setting") as save_setting:
            handler.handle_screen_saver_setting_post()

        save_setting.assert_called_once_with(SCREEN_SAVER_BOOKS, 10)
        handler.redirect_home.assert_called_once_with()

    def test_sleep_timer_toggle_post_redirects_home_after_save(self) -> None:
        body = b"enabled=1"
        handler = object.__new__(SetupHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.redirect_home = Mock()

        with patch("abs_kids_player.setup_server.save_sleep_timer_setting") as save_setting:
            handler.handle_sleep_setting_post()

        save_setting.assert_called_once_with(enabled=True)
        handler.redirect_home.assert_called_once_with()

    def test_sleep_timer_minutes_post_redirects_home_after_save(self) -> None:
        body = b"minutes=45"
        handler = object.__new__(SetupHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.redirect_home = Mock()

        with patch("abs_kids_player.setup_server.save_sleep_timer_setting") as save_setting:
            handler.handle_sleep_setting_post()

        save_setting.assert_called_once_with(minutes=45)
        handler.redirect_home.assert_called_once_with()

    def test_podcasts_post_redirects_home_after_save(self) -> None:
        body = b"podcast_url=https%3A%2F%2Fpodcasts.apple.com%2Fus%2Fpodcast%2Fexample%2Fid123"
        handler = object.__new__(SetupHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.redirect_home = Mock()

        with patch("abs_kids_player.setup_server.save_podcast_settings") as save_podcasts:
            handler.handle_podcasts_post()

        save_podcasts.assert_called_once_with(["https://podcasts.apple.com/us/podcast/example/id123"])
        handler.redirect_home.assert_called_once_with()

    def test_system_reboot_post_responds_before_scheduling_reboot(self) -> None:
        handler = object.__new__(SetupHandler)
        handler.send_page = Mock()

        with patch("abs_kids_player.setup_server.schedule_system_reboot") as schedule_reboot:
            handler.handle_system_reboot_post()

        handler.send_page.assert_called_once()
        schedule_reboot.assert_called_once_with()

    def test_system_reset_post_restores_defaults_and_schedules_setup_mode(self) -> None:
        handler = object.__new__(SetupHandler)
        handler.send_page = Mock()

        with (
            patch("abs_kids_player.setup_server.restore_device_defaults") as restore_defaults,
            patch("abs_kids_player.setup_server.schedule_system_reset") as schedule_reset,
        ):
            handler.handle_system_reset_post()

        restore_defaults.assert_called_once_with()
        handler.send_page.assert_called_once()
        schedule_reset.assert_called_once_with()

    def test_redirect_home_sends_empty_303_response(self) -> None:
        handler = object.__new__(SetupHandler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()

        handler.redirect_home()

        handler.send_response.assert_called_once_with(303)
        handler.send_header.assert_any_call("Location", "/")
        handler.send_header.assert_any_call("Content-Length", "0")
        handler.end_headers.assert_called_once_with()

    def test_audiobookshelf_form_does_not_show_library_id(self) -> None:
        self.assertNotIn("Library ID", PAGE)
        self.assertNotIn("library_id", PAGE)

    def test_admin_page_groups_controls_into_accessible_tabs(self) -> None:
        self.assertIn("<title>Chapter Player for Audiobookshelf</title>", PAGE)
        self.assertIn("<h1>Chapter Player for Audiobookshelf</h1>", PAGE)
        self.assertIn('class="app-brand"', PAGE)
        self.assertIn('class="app-logo" src="/assets/chapter-logo.png"', PAGE)
        self.assertIn('width="84" height="63" alt=""', PAGE)
        self.assertIn('<link rel="icon" type="image/png" href="/assets/chapter-logo.png">', PAGE)
        self.assertNotIn("Administration", PAGE)
        self.assertIn('role="tablist"', PAGE)
        for tab_name in ("overview", "settings", "podcasts", "connections", "system"):
            self.assertIn(f'data-tab-target="{tab_name}"', PAGE)
            self.assertIn(f'data-tab-panel="{tab_name}"', PAGE)
        self.assertIn('data-tab-target="system">System</button>', PAGE)
        self.assertNotIn('data-tab-target="reset"', PAGE)
        self.assertIn('aria-selected="true"', PAGE)
        self.assertIn('window.localStorage.setItem(tabStorageKey, tabName)', PAGE)
        self.assertIn('window.localStorage.getItem(tabStorageKey)', PAGE)
        self.assertIn('event.key === "ArrowRight"', PAGE)
        self.assertIn('event.key === "ArrowLeft"', PAGE)

    def test_system_card_shows_version_and_uses_in_page_confirmations(self) -> None:
        html = render_system_card()

        self.assertIn('<h2 id="system-heading">System</h2>', html)
        self.assertIn("Software Version", html)
        self.assertIn(f"<strong>v{__version__}</strong>", html)
        self.assertIn("Restore Device to Default Settings", html)
        self.assertIn('data-confirm-trigger="reboot"', html)
        self.assertIn('data-confirm-panel="reboot" hidden', html)
        self.assertIn("Are you sure you want to reboot?", html)
        self.assertIn('action="/system/reboot"', html)
        self.assertIn('data-confirm-trigger="restore"', html)
        self.assertIn('data-confirm-panel="restore" hidden', html)
        self.assertIn("Are you sure you want to restore the device to default settings?", html)
        self.assertIn('action="/system/reset"', html)
        self.assertNotIn("window.confirm", PAGE)

    def test_logo_asset_is_served_as_cached_png(self) -> None:
        handler = object.__new__(SetupHandler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()

        handler.send_logo_png()

        body = handler.wfile.getvalue()
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "image/png")
        handler.send_header.assert_any_call("Cache-Control", "public, max-age=86400")
        handler.send_header.assert_any_call("Content-Length", str(len(body)))
        handler.end_headers.assert_called_once_with()

    def test_admin_page_uses_sse_with_polling_fallback(self) -> None:
        self.assertIn('new EventSource("/player/events")', PAGE)
        self.assertIn("source.onmessage", PAGE)
        self.assertNotIn('addEventListener("status"', PAGE)
        self.assertNotIn("Live updates:", PAGE)
        self.assertNotIn("http-equiv=\"refresh\"", PAGE)
        self.assertNotIn("window.setInterval(refreshPlayerStatus, 5000)", PAGE)
        self.assertIn("fallbackPollTimer = window.setInterval(refreshPlayerStatus, 1000)", PAGE)
        self.assertIn("pendingPlaybackAction", PAGE)
        self.assertIn("setPendingPlayback", PAGE)
        self.assertNotIn("applyOptimisticPlayback", PAGE)

    def test_wifi_card_shows_forget_button_when_connected_to_home_wifi(self) -> None:
        html = render_wifi_card(WifiStatus(connected=True, ssid="Chapter WiFi"))

        self.assertIn("Connected to <strong>Chapter WiFi</strong>", html)
        self.assertIn("open Wi-Fi network", html)
        self.assertIn("Forget this WiFi network", html)
        self.assertNotIn("password", html.lower())
        self.assertNotIn('action="/wifi"', html)

    def test_wifi_card_shows_setup_form_when_on_setup_hotspot(self) -> None:
        html = render_wifi_card(WifiStatus(connected=True, ssid=SETUP_HOTSPOT_SSID))

        self.assertIn("open Wi-Fi network", html)
        self.assertIn("Connect to Wi-Fi", html)
        self.assertIn('action="/wifi"', html)
        self.assertNotIn("Forget this WiFi network", html)

    def test_wifi_forget_is_scheduled_after_five_second_response_window(self) -> None:
        timers = []

        class FakeTimer:
            def __init__(self, delay: float, callback) -> None:
                self.delay = delay
                self.callback = callback
                self.daemon = False
                self.started = False
                timers.append(self)

            def start(self) -> None:
                self.started = True

        with patch("abs_kids_player.setup_server.threading.Timer", FakeTimer):
            schedule_wifi_forget()

        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0].delay, WIFI_CHANGE_DELAY_SECONDS)
        self.assertTrue(timers[0].daemon)
        self.assertTrue(timers[0].started)

    def test_system_reboot_is_scheduled_after_response_window(self) -> None:
        timers = []
        commands = []

        class FakeTimer:
            def __init__(self, delay: float, callback) -> None:
                self.delay = delay
                self.callback = callback
                self.daemon = False
                timers.append(self)

            def start(self) -> None:
                pass

        with patch("abs_kids_player.setup_server.threading.Timer", FakeTimer):
            schedule_system_reboot(runner=lambda command: commands.append(command))

        self.assertEqual(timers[0].delay, SYSTEM_ACTION_DELAY_SECONDS)
        self.assertTrue(timers[0].daemon)
        timers[0].callback()
        self.assertEqual(commands, [["systemctl", "reboot"]])

    def test_system_reset_is_scheduled_after_response_window(self) -> None:
        timers = []

        class FakeTimer:
            def __init__(self, delay: float, callback) -> None:
                self.delay = delay
                self.callback = callback
                self.daemon = False
                timers.append(self)

            def start(self) -> None:
                pass

        with (
            patch("abs_kids_player.setup_server.threading.Timer", FakeTimer),
            patch(
                "abs_kids_player.setup_server.forget_all_wifi_connections_and_start_hotspot"
            ) as forget_wifi,
        ):
            schedule_system_reset()
            timers[0].callback()

        self.assertEqual(timers[0].delay, WIFI_CHANGE_DELAY_SECONDS)
        self.assertTrue(timers[0].daemon)
        forget_wifi.assert_called_once_with()

    def test_restore_device_defaults_clears_player_data_and_refreshes_library(self) -> None:
        with (
            patch("abs_kids_player.setup_server.save_config") as save_config,
            patch("abs_kids_player.setup_server.clear_cached_books") as clear_cache,
            patch("abs_kids_player.setup_server.clear_last_playback") as clear_playback,
            patch("abs_kids_player.setup_server.queue_web_player_command") as queue_command,
        ):
            config = restore_device_defaults()

        self.assertFalse(config.is_ready)
        self.assertTrue(config.control_click_enabled)
        self.assertFalse(config.sleep_timer_enabled)
        save_config.assert_called_once_with(config)
        clear_cache.assert_called_once_with()
        clear_playback.assert_called_once_with()
        queue_command.assert_called_once_with("refresh_library")

    def test_login_username_prefers_server_response(self) -> None:
        self.assertEqual(login_username({"user": {"username": "chapter"}}, "fallback"), "chapter")
        self.assertEqual(login_username({"user": {}}, "fallback"), "fallback")

    def test_login_and_refresh_player_saves_new_user_library_and_queues_refresh(self) -> None:
        with (
            patch(
                "abs_kids_player.setup_server.load_config",
                return_value=AppConfig(control_click_enabled=False, screen_saver_mode=SCREEN_SAVER_BOOKS),
            ),
            patch("abs_kids_player.setup_server.AudiobookshelfClient", FakeAudiobookshelfClient),
            patch("abs_kids_player.setup_server.save_config") as save_config,
            patch("abs_kids_player.setup_server.queue_web_player_command") as queue_command,
        ):
            config = login_and_refresh_player("https://books.example.com", "chapter", "password")

        self.assertEqual(config.server_url, "https://books.example.com")
        self.assertEqual(config.refresh_token, "refresh-token")
        self.assertEqual(config.library_id, "library-1")
        self.assertEqual(config.username, "chapter")
        self.assertFalse(config.control_click_enabled)
        self.assertEqual(config.screen_saver_mode, SCREEN_SAVER_BOOKS)
        save_config.assert_called_once_with(config)
        self.assertEqual(
            [call.args for call in queue_command.call_args_list],
            [("pause",), ("refresh_library",)],
        )

    def test_saved_username_treats_unknown_user_as_missing(self) -> None:
        self.assertEqual(saved_username("unknown user"), "")
        self.assertEqual(saved_username(" chapter "), "chapter")

    def test_audiobookshelf_status_recovers_missing_username(self) -> None:
        config = AppConfig(server_url="https://books.example.com", token="token", library_id="library-1")

        with (
            patch("abs_kids_player.setup_server.load_config", return_value=config),
            patch("abs_kids_player.setup_server.AudiobookshelfClient", FakeAudiobookshelfClient),
            patch("abs_kids_player.setup_server.save_config") as save_config,
        ):
            ok, message = audiobookshelf_status()

        self.assertTrue(ok)
        self.assertEqual(message, "Logged in to https://books.example.com as chapter")
        saved = save_config.call_args.args[0]
        self.assertEqual(saved.username, "chapter")


if __name__ == "__main__":
    unittest.main()
