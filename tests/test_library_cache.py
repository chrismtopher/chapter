from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abs_kids_player.config import AppConfig, PodcastConfig
from abs_kids_player.library_cache import clear_cached_books, library_cache_path, load_cached_books, save_cached_books
from abs_kids_player.models import Book


class LibraryCacheTest(unittest.TestCase):
    def make_config(self, username: str = "chapter") -> AppConfig:
        return AppConfig(
            server_url="https://books.example.com",
            token="secret-token",
            library_id="library-1",
            username=username,
            podcasts=[PodcastConfig(url="https://podcasts.apple.com/example")],
        )

    def test_round_trips_books_without_storing_cover_token(self) -> None:
        config = self.make_config()
        books = [
            Book(
                id="book-1",
                title="The Hobbit",
                author="J.R.R. Tolkien",
                duration=3600,
                cover_url="https://books.example.com/cover?token=secret-token",
                current_time=120,
                progress=0.04,
                series_name="Middle-earth",
                series_sequence="1",
                series_total=3,
            )
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library-cache.json"
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_LIBRARY_CACHE_PATH": str(path)}):
                save_cached_books(config, books)
                cached = load_cached_books(config)
                raw_cache = path.read_text(encoding="utf-8")

        self.assertEqual(cached[0].title, "The Hobbit")
        self.assertEqual(cached[0].display_title, "Middle-earth: The Hobbit")
        self.assertEqual(cached[0].current_time, 120)
        self.assertEqual(cached[0].cover_url, "")
        self.assertEqual(cached[0].series_position, "1/3")
        self.assertNotIn("secret-token", raw_cache)

    def test_does_not_load_cache_for_a_different_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library-cache.json"
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_LIBRARY_CACHE_PATH": str(path)}):
                save_cached_books(
                    self.make_config("chapter"),
                    [Book("book-1", "The Hobbit", "J.R.R. Tolkien", 3600, "")],
                )
                cached = load_cached_books(self.make_config("another-user"))

        self.assertEqual(cached, [])

    def test_clear_cached_books_removes_cache_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library-cache.json"
            path.write_text("{}", encoding="utf-8")
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_LIBRARY_CACHE_PATH": str(path)}):
                clear_cached_books()

            self.assertFalse(path.exists())

    def test_state_dir_environment_override_is_used_for_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_STATE_DIR": directory}):
                self.assertEqual(library_cache_path(), Path(directory) / "library-cache.json")


if __name__ == "__main__":
    unittest.main()
