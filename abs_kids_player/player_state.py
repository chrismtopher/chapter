from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .storage import ensure_storage_directory, finalize_storage_file


STATE_DIR = Path.home() / ".local" / "state" / "abs-kids-player"
STATE_PATH = STATE_DIR / "player-state.json"


@dataclass(frozen=True)
class LastPlaybackState:
    book_id: str
    title: str
    current_time: float = 0
    updated_at: float = 0

    @property
    def is_ready(self) -> bool:
        return bool(self.book_id.strip() and self.title.strip())


def load_player_state() -> LastPlaybackState | None:
    path = state_path()
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    state = LastPlaybackState(
        book_id=str(data.get("book_id", "")),
        title=str(data.get("title", "")),
        current_time=float(data.get("current_time") or 0),
        updated_at=float(data.get("updated_at") or 0),
    )
    return state if state.is_ready else None


def save_last_playback(book_id: str, title: str, current_time: float, now: float | None = None) -> None:
    state = LastPlaybackState(
        book_id=book_id,
        title=title,
        current_time=max(0.0, current_time),
        updated_at=time.time() if now is None else now,
    )
    if not state.is_ready:
        return

    path = state_path()
    ensure_storage_directory(path.parent)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    finalize_storage_file(path)


def clear_last_playback() -> None:
    try:
        state_path().unlink(missing_ok=True)
    except OSError:
        pass


def state_path() -> Path:
    configured_path = os.environ.get("ABS_KIDS_PLAYER_STATE_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()

    configured_dir = os.environ.get("ABS_KIDS_PLAYER_STATE_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / "player-state.json"

    return STATE_PATH
