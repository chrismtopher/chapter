from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .storage import ensure_storage_directory, finalize_storage_file


STATE_DIR = Path.home() / ".local" / "state" / "abs-kids-player"
STATUS_PATH = STATE_DIR / "web-player-status.json"
COMMANDS_PATH = STATE_DIR / "web-player-commands.json"


@dataclass(frozen=True)
class WebPlayerStatus:
    title: str = ""
    author: str = ""
    current_time: float = 0
    duration: float = 0
    is_playing: bool = False
    volume_percent: int = 50
    muted: bool = False
    updated_at: float = 0

    @property
    def has_session(self) -> bool:
        return bool(self.title.strip())


@dataclass(frozen=True)
class WebPlayerCommand:
    action: str
    value: int | None = None
    id: str = ""
    created_at: float = 0


def save_web_player_status(status: WebPlayerStatus) -> None:
    path = status_path()
    ensure_storage_directory(path.parent)
    data = asdict(status)
    data["updated_at"] = time.time()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    finalize_storage_file(path)


def load_web_player_status() -> WebPlayerStatus:
    try:
        data = json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return WebPlayerStatus()

    return WebPlayerStatus(
        title=str(data.get("title", "")),
        author=str(data.get("author", "")),
        current_time=float(data.get("current_time") or 0),
        duration=float(data.get("duration") or 0),
        is_playing=bool(data.get("is_playing")),
        volume_percent=clamp_int(data.get("volume_percent"), 0, 100, 50),
        muted=bool(data.get("muted")),
        updated_at=float(data.get("updated_at") or 0),
    )


def queue_web_player_command(action: str, value: int | None = None) -> WebPlayerCommand:
    command = WebPlayerCommand(
        action=action,
        value=value,
        id=uuid.uuid4().hex,
        created_at=time.time(),
    )
    commands = read_command_data()
    commands.append(asdict(command))
    write_command_data(commands)
    return command


def consume_web_player_commands() -> list[WebPlayerCommand]:
    commands = [
        WebPlayerCommand(
            action=str(item.get("action", "")),
            value=item.get("value") if isinstance(item.get("value"), int) else None,
            id=str(item.get("id", "")),
            created_at=float(item.get("created_at") or 0),
        )
        for item in read_command_data()
        if isinstance(item, dict)
    ]
    write_command_data([])
    return [command for command in commands if command.action]


def read_command_data() -> list[dict[str, Any]]:
    try:
        data = json.loads(commands_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def write_command_data(commands: list[dict[str, Any]]) -> None:
    path = commands_path()
    ensure_storage_directory(path.parent)
    path.write_text(json.dumps(commands, indent=2), encoding="utf-8")
    finalize_storage_file(path)


def status_path() -> Path:
    configured_path = os.environ.get("ABS_KIDS_PLAYER_WEB_STATUS_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    configured_dir = os.environ.get("ABS_KIDS_PLAYER_STATE_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / STATUS_PATH.name
    return STATUS_PATH


def commands_path() -> Path:
    configured_path = os.environ.get("ABS_KIDS_PLAYER_WEB_COMMANDS_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    configured_dir = os.environ.get("ABS_KIDS_PLAYER_STATE_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / COMMANDS_PATH.name
    return COMMANDS_PATH


def clamp_int(value: object, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(parsed, minimum), maximum)
