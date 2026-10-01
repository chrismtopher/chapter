from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from abs_kids_player.config import AppConfig, save_config
from abs_kids_player.player_control import queue_web_player_command


class StorageOwnershipTest(unittest.TestCase):
    def test_root_config_save_hands_directory_and_file_to_service_user(self) -> None:
        owner = SimpleNamespace(pw_uid=123, pw_gid=456)
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            with (
                patch.dict(
                    "os.environ",
                    {
                        "ABS_KIDS_PLAYER_CONFIG_DIR": str(config_dir),
                        "ABS_KIDS_PLAYER_STORAGE_OWNER": "chapter",
                    },
                ),
                patch("abs_kids_player.storage.configured_storage_owner", return_value=owner),
                patch("abs_kids_player.storage.os.chown") as chown,
            ):
                save_config(AppConfig(server_url="https://books.example.com", token="token"))

            config_path = config_dir / "config.json"
            self.assertEqual(config_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
            chown.assert_any_call(config_dir, 123, 456)
            chown.assert_any_call(config_path, 123, 456)

    def test_root_web_command_is_handed_to_service_user(self) -> None:
        owner = SimpleNamespace(pw_uid=123, pw_gid=456)
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            with (
                patch.dict(
                    "os.environ",
                    {
                        "ABS_KIDS_PLAYER_STATE_DIR": str(state_dir),
                        "ABS_KIDS_PLAYER_STORAGE_OWNER": "chapter",
                    },
                ),
                patch("abs_kids_player.storage.configured_storage_owner", return_value=owner),
                patch("abs_kids_player.storage.os.chown") as chown,
            ):
                queue_web_player_command("pause")

            command_path = state_dir / "web-player-commands.json"
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(command_path.stat().st_mode & 0o777, 0o600)
            chown.assert_any_call(state_dir, 123, 456)
            chown.assert_any_call(command_path, 123, 456)


if __name__ == "__main__":
    unittest.main()
