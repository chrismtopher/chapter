from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abs_kids_player.config import (
    DEFAULT_SCREEN_SAVER_DIM_PERCENT,
    DEFAULT_SLEEP_TIMER_MINUTES,
    MAX_SLEEP_TIMER_MINUTES,
    SCREEN_SAVER_BOOKS,
    SCREEN_SAVER_CHAPTER,
    SCREEN_SAVER_DIM_LEVELS,
    AppConfig,
    PodcastConfig,
    config_path,
    load_config,
    save_config,
    valid_screen_saver_dim_percent,
    valid_sleep_timer_minutes,
)


class ConfigTest(unittest.TestCase):
    def test_config_dir_environment_override_is_used_for_load_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                save_config(AppConfig(server_url="https://books.example.com", token="token", username="chapter"))

                path = Path(temp_dir) / "config.json"
                self.assertEqual(config_path(), path)
                self.assertTrue(path.exists())
                self.assertEqual(load_config().username, "chapter")
                self.assertTrue(load_config().control_click_enabled)

    def test_config_saves_control_click_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                save_config(AppConfig(control_click_enabled=False))

                self.assertFalse(load_config().control_click_enabled)

    def test_config_saves_screen_saver_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                save_config(AppConfig(screen_saver_mode=SCREEN_SAVER_BOOKS))

                self.assertEqual(load_config().screen_saver_mode, SCREEN_SAVER_BOOKS)

    def test_config_saves_screen_saver_dim_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                save_config(AppConfig(screen_saver_dim_percent=10))

                self.assertEqual(load_config().screen_saver_dim_percent, 10)

    def test_screen_saver_dim_level_defaults_and_validates(self) -> None:
        self.assertEqual(AppConfig().screen_saver_dim_percent, DEFAULT_SCREEN_SAVER_DIM_PERCENT)
        self.assertEqual(valid_screen_saver_dim_percent(None), DEFAULT_SCREEN_SAVER_DIM_PERCENT)
        self.assertEqual(valid_screen_saver_dim_percent(10), 10)
        self.assertEqual(valid_screen_saver_dim_percent(99), DEFAULT_SCREEN_SAVER_DIM_PERCENT)
        self.assertIn(DEFAULT_SCREEN_SAVER_DIM_PERCENT, SCREEN_SAVER_DIM_LEVELS)

    def test_sleep_timer_is_disabled_by_default(self) -> None:
        config = AppConfig()

        self.assertFalse(config.sleep_timer_enabled)
        self.assertEqual(config.sleep_timer_minutes, DEFAULT_SLEEP_TIMER_MINUTES)

    def test_config_saves_sleep_timer_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                save_config(AppConfig(sleep_timer_enabled=True, sleep_timer_minutes=45))
                config = load_config()

        self.assertTrue(config.sleep_timer_enabled)
        self.assertEqual(config.sleep_timer_minutes, 45)

    def test_sleep_timer_minutes_are_validated(self) -> None:
        self.assertEqual(valid_sleep_timer_minutes("not-a-number"), DEFAULT_SLEEP_TIMER_MINUTES)
        self.assertEqual(valid_sleep_timer_minutes(0), 1)
        self.assertEqual(valid_sleep_timer_minutes(999), MAX_SLEEP_TIMER_MINUTES)

    def test_config_saves_podcasts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                save_config(
                    AppConfig(
                        podcasts=[
                            PodcastConfig(
                                url="https://podcasts.apple.com/us/podcast/example/id123",
                                title="Example Show",
                                author="Example Parent",
                                feed_url="https://feeds.example.com/show.xml",
                                book_id="podcast:apple:123",
                            )
                        ]
                    )
                )

                podcast = load_config().podcasts[0]

        self.assertEqual(podcast.title, "Example Show")
        self.assertEqual(podcast.author, "Example Parent")
        self.assertEqual(podcast.feed_url, "https://feeds.example.com/show.xml")
        self.assertEqual(podcast.book_id, "podcast:apple:123")

    def test_old_config_gets_default_podcasts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text('{"server_url": "https://books.example.com"}', encoding="utf-8")
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                titles = [podcast.title for podcast in load_config().podcasts]

        self.assertEqual(titles, ["Yoto Daily", "Trivia for Kids"])

    def test_saved_empty_podcast_list_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text('{"podcasts": []}', encoding="utf-8")
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                self.assertEqual(load_config().podcasts, [])

    def test_config_falls_back_to_chapter_screen_saver_for_unknown_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text('{"screen_saver_mode": "unknown"}', encoding="utf-8")
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                self.assertEqual(load_config().screen_saver_mode, SCREEN_SAVER_CHAPTER)

    def test_old_config_gets_default_screen_saver_dim_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text('{"screen_saver_mode": "clock"}', encoding="utf-8")
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_CONFIG_DIR": temp_dir}, clear=False):
                self.assertEqual(load_config().screen_saver_dim_percent, DEFAULT_SCREEN_SAVER_DIM_PERCENT)


if __name__ == "__main__":
    unittest.main()
