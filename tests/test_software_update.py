from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abs_kids_player.software_update import (
    ReleaseCheck,
    SoftwareUpdateState,
    check_for_update,
    install_latest_release,
    latest_release_tag,
    load_update_state,
    save_update_state,
    update_status_payload,
    version_tuple,
)


RELEASES = """\
1111111111111111111111111111111111111111\trefs/tags/v0.2.2
2222222222222222222222222222222222222222\trefs/tags/v0.3.0
3333333333333333333333333333333333333333\trefs/tags/v0.3.0-rc1
4444444444444444444444444444444444444444\trefs/tags/not-a-release
"""


class SoftwareUpdateTest(unittest.TestCase):
    def test_version_parser_only_accepts_stable_semantic_versions(self) -> None:
        self.assertEqual(version_tuple("v1.2.3"), (1, 2, 3))
        self.assertEqual(version_tuple("1.2.3"), (1, 2, 3))
        self.assertIsNone(version_tuple("1.2"))
        self.assertIsNone(version_tuple("v1.2.3-rc1"))

    def test_latest_release_tag_ignores_non_stable_tags(self) -> None:
        self.assertEqual(latest_release_tag(RELEASES), "v0.3.0")

    def test_check_for_update_reports_newer_release(self) -> None:
        commands = []

        def runner(args, **_kwargs):
            commands.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=RELEASES, stderr="")

        result = check_for_update(
            current_version="0.2.2",
            repo_url="https://example.test/chapter.git",
            runner=runner,
        )

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "0.3.0")
        self.assertEqual(
            commands,
            [["git", "ls-remote", "--refs", "--tags", "https://example.test/chapter.git", "v*"]],
        )

    def test_check_for_update_returns_a_safe_network_error(self) -> None:
        def runner(_args, **_kwargs):
            raise subprocess.TimeoutExpired("git", 15)

        result = check_for_update(current_version="0.2.2", runner=runner)

        self.assertFalse(result.update_available)
        self.assertEqual(result.error, "Unable to reach the Chapter release repository.")

    def test_update_state_round_trip_uses_configured_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            state = SoftwareUpdateState(
                phase="installing",
                target_version="0.3.0",
                message="Installing v0.3.0.",
                updated_at=123.0,
            )
            with patch.dict(os.environ, {"ABS_KIDS_PLAYER_STATE_DIR": temporary_dir}):
                save_update_state(state)
                loaded = load_update_state()

            self.assertEqual(loaded, state)
            self.assertEqual((Path(temporary_dir) / "software-update.json").stat().st_mode & 0o777, 0o600)

    def test_status_payload_preserves_failed_update_message(self) -> None:
        with (
            patch(
                "abs_kids_player.software_update.load_update_state",
                return_value=SoftwareUpdateState(
                    phase="failed",
                    target_version="0.3.0",
                    message="Update failed: package error",
                ),
            ),
            patch(
                "abs_kids_player.software_update.check_for_update",
                return_value=ReleaseCheck(
                    current_version="0.2.2",
                    latest_version="0.3.0",
                    update_available=True,
                ),
            ),
        ):
            payload = update_status_payload()

        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["message"], "Update failed: package error")
        self.assertTrue(payload["updateAvailable"])

    def test_status_payload_recovers_from_stale_installing_state(self) -> None:
        with (
            patch(
                "abs_kids_player.software_update.load_update_state",
                return_value=SoftwareUpdateState(
                    phase="installing",
                    target_version="0.3.0",
                    message="Installing v0.3.0.",
                    updated_at=1.0,
                ),
            ),
            patch("abs_kids_player.software_update.time.time", return_value=10_000.0),
            patch(
                "abs_kids_player.software_update.check_for_update",
                return_value=ReleaseCheck(
                    current_version="0.2.2",
                    latest_version="0.3.0",
                    update_available=True,
                ),
            ),
        ):
            payload = update_status_payload()

        self.assertEqual(payload["phase"], "failed")
        self.assertTrue(payload["updateAvailable"])
        self.assertIn("did not finish", payload["message"])

    def test_installer_fetches_target_release_installer_and_restarts_services(self) -> None:
        commands = []

        def runner(args, **_kwargs):
            commands.append(args)
            if args[:2] == ["git", "ls-remote"]:
                return subprocess.CompletedProcess(args, 0, stdout=RELEASES, stderr="")
            if "show" in args:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout="#!/usr/bin/env bash\nexit 0\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with (
            tempfile.TemporaryDirectory() as temporary_dir,
            patch.dict(os.environ, {"ABS_KIDS_PLAYER_STATE_DIR": temporary_dir}),
            patch("abs_kids_player.software_update.os.geteuid", return_value=1000),
        ):
            installed = install_latest_release(
                runner=runner,
                repo_url="https://example.test/chapter.git",
                install_user="chapter",
                install_dir="/home/chapter/audiobookshelf-player",
            )
            state = load_update_state()

        self.assertEqual(installed, "0.3.0")
        self.assertEqual(state.phase, "completed")
        self.assertIn(
            [
                "git",
                "-C",
                "/home/chapter/audiobookshelf-player",
                "fetch",
                "--force",
                "--tags",
                "origin",
            ],
            commands,
        )
        self.assertIn(
            [
                "git",
                "-C",
                "/home/chapter/audiobookshelf-player",
                "show",
                "v0.3.0:scripts/install-raspberry-pi.sh",
            ],
            commands,
        )
        installer_command = next(command for command in commands if command[0] == "bash")
        self.assertIn("--release-ref", installer_command)
        self.assertIn("v0.3.0", installer_command)
        self.assertIn("--no-reboot", installer_command)
        self.assertIn(
            ["systemctl", "restart", "audiobookshelf-player-oled.service"],
            commands,
        )
        self.assertIn(
            ["systemctl", "restart", "audiobookshelf-player-setup.service"],
            commands,
        )


if __name__ == "__main__":
    unittest.main()
