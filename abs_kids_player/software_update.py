from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .storage import ensure_storage_directory, finalize_storage_file


DEFAULT_REPO_URL = "https://github.com/chrismtopher/chapter.git"
DEFAULT_INSTALL_USER = "chapter"
DEFAULT_INSTALL_DIR = "/home/chapter/audiobookshelf-player"
UPDATE_SERVICE_NAME = "audiobookshelf-player-update.service"
UPDATE_STATE_FILENAME = "software-update.json"
RELEASE_TAG_PATTERN = re.compile(r"^refs/tags/v(\d+)\.(\d+)\.(\d+)$")
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
UPDATE_CHECK_TIMEOUT_SECONDS = 15
UPDATE_INSTALL_TIMEOUT_SECONDS = 45 * 60
STALE_UPDATE_SECONDS = 60 * 60

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ReleaseCheck:
    current_version: str
    latest_version: str = ""
    update_available: bool = False
    error: str = ""


@dataclass(frozen=True)
class SoftwareUpdateState:
    phase: str = "idle"
    target_version: str = ""
    message: str = ""
    updated_at: float = 0.0
    display_ready: bool = False


def run_command(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, check=True, text=True, **kwargs)


def version_tuple(value: str) -> tuple[int, int, int] | None:
    match = VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def latest_release_tag(output: str) -> str:
    versions: list[tuple[tuple[int, int, int], str]] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        match = RELEASE_TAG_PATTERN.fullmatch(fields[1])
        if match is None:
            continue
        version = tuple(int(part) for part in match.groups())
        versions.append((version, f"v{'.'.join(match.groups())}"))
    return max(versions)[1] if versions else ""


def check_for_update(
    current_version: str = __version__,
    repo_url: str | None = None,
    runner: CommandRunner = run_command,
) -> ReleaseCheck:
    repo_url = repo_url or os.environ.get("CHAPTER_REPO_URL", DEFAULT_REPO_URL)
    current = version_tuple(current_version)
    if current is None:
        return ReleaseCheck(current_version=current_version, error="Invalid installed version.")
    try:
        result = runner(
            ["git", "ls-remote", "--refs", "--tags", repo_url, "v*"],
            timeout=UPDATE_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ReleaseCheck(
            current_version=current_version,
            error="Unable to reach the Chapter release repository.",
        )
    latest_tag = latest_release_tag(result.stdout)
    latest = version_tuple(latest_tag)
    if latest is None:
        return ReleaseCheck(
            current_version=current_version,
            error="No stable Chapter releases were found.",
        )
    return ReleaseCheck(
        current_version=current_version,
        latest_version=latest_tag.removeprefix("v"),
        update_available=latest > current,
    )


def update_status_payload() -> dict:
    state = load_update_state()
    update_is_active = update_state_is_active(state)
    if update_is_active:
        return {
            "currentVersion": __version__,
            "latestVersion": state.target_version,
            "updateAvailable": False,
            "phase": state.phase,
            "message": state.message or "Installing the software update.",
        }

    release = check_for_update()
    message = ""
    phase = "available" if release.update_available else "current"
    if release.error:
        phase = "error"
        message = release.error
    elif state.phase == "installing":
        phase = "failed"
        message = "The previous update did not finish. You can try installing it again."
    elif state.phase == "failed":
        phase = "failed"
        message = state.message or "The previous software update failed."
    elif state.phase == "completed" and state.target_version == release.current_version:
        phase = "completed"
        message = state.message or f"Updated successfully to v{release.current_version}."
    return {
        "currentVersion": release.current_version,
        "latestVersion": release.latest_version,
        "updateAvailable": release.update_available,
        "phase": phase,
        "message": message,
    }


def update_state_is_active(
    state: SoftwareUpdateState,
    now: float | None = None,
) -> bool:
    current_time = time.time() if now is None else now
    return (
        state.phase == "installing"
        and state.updated_at > 0
        and current_time - state.updated_at < STALE_UPDATE_SECONDS
    )


def update_state_path() -> Path:
    configured_dir = os.environ.get("ABS_KIDS_PLAYER_STATE_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / UPDATE_STATE_FILENAME
    return Path.home() / ".local" / "state" / "abs-kids-player" / UPDATE_STATE_FILENAME


def load_update_state() -> SoftwareUpdateState:
    path = update_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SoftwareUpdateState()
    return SoftwareUpdateState(
        phase=str(data.get("phase", "idle")),
        target_version=str(data.get("target_version", "")),
        message=str(data.get("message", "")),
        updated_at=float(data.get("updated_at") or 0),
        display_ready=bool(data.get("display_ready")),
    )


def save_update_state(state: SoftwareUpdateState) -> None:
    path = update_state_path()
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    ensure_storage_directory(path.parent)
    try:
        temporary_path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
        finalize_storage_file(temporary_path)
        temporary_path.replace(path)
        finalize_storage_file(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def mark_update_display_ready() -> bool:
    state = load_update_state()
    if state.phase != "installing":
        return False
    if state.display_ready:
        return True
    save_update_state(
        SoftwareUpdateState(
            phase=state.phase,
            target_version=state.target_version,
            message=state.message,
            updated_at=state.updated_at,
            display_ready=True,
        )
    )
    return True


def wait_for_update_display_ready(
    timeout_seconds: float = 12.0,
    poll_seconds: float = 0.1,
    state_loader: Callable[[], SoftwareUpdateState] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    load_state = state_loader or load_update_state
    deadline = clock() + max(0.0, timeout_seconds)
    while True:
        state = load_state()
        if state.phase != "installing":
            return False
        if state.display_ready:
            return True
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        sleeper(min(max(poll_seconds, 0.01), remaining))


def command_for_install_user(args: list[str], install_user: str) -> list[str]:
    if os.geteuid() != 0:
        return args
    account = pwd.getpwnam(install_user)
    return [
        "runuser",
        "-u",
        install_user,
        "--",
        "env",
        f"HOME={account.pw_dir}",
        *args,
    ]


def concise_error(error: BaseException) -> str:
    if isinstance(error, subprocess.CalledProcessError):
        detail = (error.stderr or error.stdout or "").strip().splitlines()
        if detail:
            return detail[-1][:240]
    return str(error)[:240] or "Unknown update error."


def install_latest_release(
    runner: CommandRunner = run_command,
    repo_url: str | None = None,
    install_user: str | None = None,
    install_dir: str | None = None,
) -> str:
    repo_url = repo_url or os.environ.get("CHAPTER_REPO_URL", DEFAULT_REPO_URL)
    install_user = install_user or os.environ.get("CHAPTER_INSTALL_USER", DEFAULT_INSTALL_USER)
    install_dir = install_dir or os.environ.get("CHAPTER_INSTALL_DIR", DEFAULT_INSTALL_DIR)
    release = check_for_update(repo_url=repo_url, runner=runner)
    if release.error:
        save_update_state(
            SoftwareUpdateState(
                phase="failed",
                message=f"Update failed: {release.error}",
                updated_at=time.time(),
            )
        )
        raise RuntimeError(release.error)
    if not release.update_available:
        save_update_state(
            SoftwareUpdateState(
                phase="completed",
                target_version=release.current_version,
                message=f"v{release.current_version} is already up to date.",
                updated_at=time.time(),
            )
        )
        return release.current_version

    target_tag = f"v{release.latest_version}"
    save_update_state(
        SoftwareUpdateState(
            phase="installing",
            target_version=release.latest_version,
            message=f"Installing {target_tag}. The player will restart when it is ready.",
            updated_at=time.time(),
        )
    )
    try:
        runner(
            command_for_install_user(
                ["git", "-C", install_dir, "fetch", "--force", "--tags", "origin"],
                install_user,
            ),
            timeout=120,
        )
        installer = runner(
            command_for_install_user(
                ["git", "-C", install_dir, "show", f"{target_tag}:scripts/install-raspberry-pi.sh"],
                install_user,
            ),
            timeout=30,
        ).stdout
        if not installer.startswith("#!/usr/bin/env bash"):
            raise RuntimeError("The release installer could not be verified.")

        with tempfile.TemporaryDirectory(prefix="chapter-update-") as temporary_dir:
            installer_path = Path(temporary_dir) / "install-raspberry-pi.sh"
            installer_path.write_text(installer, encoding="utf-8")
            installer_path.chmod(0o700)
            runner(
                [
                    "bash",
                    str(installer_path),
                    "--release-ref",
                    target_tag,
                    "--repo-url",
                    repo_url,
                    "--user",
                    install_user,
                    "--install-dir",
                    install_dir,
                    "--no-reboot",
                ],
                timeout=UPDATE_INSTALL_TIMEOUT_SECONDS,
            )

        save_update_state(
            SoftwareUpdateState(
                phase="completed",
                target_version=release.latest_version,
                message=f"Updated successfully to {target_tag}.",
                updated_at=time.time(),
            )
        )
        runner(["systemctl", "restart", "audiobookshelf-player-oled.service"], timeout=30)
        runner(["systemctl", "restart", "audiobookshelf-player-setup.service"], timeout=30)
        return release.latest_version
    except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        save_update_state(
            SoftwareUpdateState(
                phase="failed",
                target_version=release.latest_version,
                message=f"Update failed: {concise_error(error)}",
                updated_at=time.time(),
            )
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Check for and install Chapter software updates.")
    parser.add_argument("command", choices=("check", "install"))
    args = parser.parse_args()
    if args.command == "check":
        print(json.dumps(update_status_payload(), indent=2))
        return
    installed_version = install_latest_release()
    print(f"Chapter Player v{installed_version} is installed.", flush=True)


if __name__ == "__main__":
    main()
