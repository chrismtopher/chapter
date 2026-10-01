from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abs_kids_player.player_state import clear_last_playback, load_player_state, save_last_playback


class PlayerStateTest(unittest.TestCase):
    def test_save_and_load_last_playback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_STATE_PATH": str(path)}):
                save_last_playback("book-1", "The Hobbit", 123.4, now=55.0)

                state = load_player_state()

        self.assertIsNotNone(state)
        self.assertEqual(state.book_id, "book-1")
        self.assertEqual(state.title, "The Hobbit")
        self.assertEqual(state.current_time, 123.4)
        self.assertEqual(state.updated_at, 55.0)

    def test_invalid_last_playback_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"book_id": "", "title": "Missing"}', encoding="utf-8")

            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_STATE_PATH": str(path)}):
                state = load_player_state()

        self.assertIsNone(state)

    def test_clear_last_playback_removes_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.dict("os.environ", {"ABS_KIDS_PLAYER_STATE_PATH": str(path)}):
                save_last_playback("book-1", "The Hobbit", 1)
                clear_last_playback()

                self.assertIsNone(load_player_state())
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
