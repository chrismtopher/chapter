from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .storage import ensure_storage_directory, finalize_storage_file


CONFIG_DIR = Path.home() / ".config" / "abs-kids-player"
CONFIG_PATH = CONFIG_DIR / "config.json"
SCREEN_SAVER_CHAPTER = "chapter"
SCREEN_SAVER_BOOKS = "books"
SCREEN_SAVER_CLOCK = "clock"
SCREEN_SAVER_MODES = (SCREEN_SAVER_CHAPTER, SCREEN_SAVER_BOOKS, SCREEN_SAVER_CLOCK)
LIBRARY_SORT_TITLE = "title"
LIBRARY_SORT_AUTHOR = "author"
LIBRARY_SORT_MODES = (LIBRARY_SORT_TITLE, LIBRARY_SORT_AUTHOR)
SCREEN_SAVER_DIM_LEVELS = (10, 15, 20, 25, 35, 50)
DEFAULT_SCREEN_SAVER_DIM_PERCENT = 15
DEFAULT_SLEEP_TIMER_MINUTES = 30
MIN_SLEEP_TIMER_MINUTES = 1
MAX_SLEEP_TIMER_MINUTES = 240
_CONFIG_LOCK = threading.RLock()


@dataclass(frozen=True)
class PodcastConfig:
    url: str
    title: str = ""
    author: str = ""
    feed_url: str = ""
    book_id: str = ""


def default_podcasts() -> list[PodcastConfig]:
    return []


@dataclass
class AppConfig:
    server_url: str = ""
    token: str = ""
    refresh_token: str = ""
    library_id: str = ""
    username: str = ""
    control_click_enabled: bool = True
    spoken_navigation_enabled: bool = False
    library_sort_mode: str = LIBRARY_SORT_TITLE
    screen_saver_mode: str = SCREEN_SAVER_CHAPTER
    screen_saver_dim_percent: int = DEFAULT_SCREEN_SAVER_DIM_PERCENT
    sleep_timer_enabled: bool = False
    sleep_timer_minutes: int = DEFAULT_SLEEP_TIMER_MINUTES
    podcasts: list[PodcastConfig] = field(default_factory=default_podcasts)

    @property
    def is_ready(self) -> bool:
        return bool(self.server_url.strip() and self.token.strip())


def load_config() -> AppConfig:
    with _CONFIG_LOCK:
        path = config_path()
        if not path.exists():
            return AppConfig()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppConfig()

    return AppConfig(
        server_url=str(data.get("server_url", "")),
        token=str(data.get("token", "")),
        refresh_token=str(data.get("refresh_token", "")),
        library_id=str(data.get("library_id", "")),
        username=str(data.get("username", "")),
        control_click_enabled=bool(data.get("control_click_enabled", True)),
        spoken_navigation_enabled=bool(data.get("spoken_navigation_enabled", False)),
        library_sort_mode=valid_library_sort_mode(str(data.get("library_sort_mode", ""))),
        screen_saver_mode=valid_screen_saver_mode(str(data.get("screen_saver_mode", ""))),
        screen_saver_dim_percent=valid_screen_saver_dim_percent(data.get("screen_saver_dim_percent")),
        sleep_timer_enabled=bool(data.get("sleep_timer_enabled", False)),
        sleep_timer_minutes=valid_sleep_timer_minutes(data.get("sleep_timer_minutes")),
        podcasts=podcast_configs_from_json(data["podcasts"]) if "podcasts" in data else default_podcasts(),
    )


def save_config(config: AppConfig) -> None:
    with _CONFIG_LOCK:
        path = config_path()
        temporary_path = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        ensure_storage_directory(path.parent)
        try:
            temporary_path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
            finalize_storage_file(temporary_path)
            temporary_path.replace(path)
            finalize_storage_file(path)
        finally:
            temporary_path.unlink(missing_ok=True)


def saved_auth_tokens(server_url: str, username: str) -> tuple[str, str]:
    with _CONFIG_LOCK:
        config = load_config()
        if not same_login(config, server_url, username):
            return "", ""
        return config.token, config.refresh_token


def update_auth_tokens(
    server_url: str,
    username: str,
    token: str,
    refresh_token: str,
) -> bool:
    with _CONFIG_LOCK:
        config = load_config()
        if not same_login(config, server_url, username):
            return False
        if config.token == token and config.refresh_token == refresh_token:
            return True
        save_config(replace(config, token=token, refresh_token=refresh_token))
        return True


def same_login(config: AppConfig, server_url: str, username: str) -> bool:
    configured_server = config.server_url.strip().rstrip("/").casefold()
    expected_server = server_url.strip().rstrip("/").casefold()
    configured_username = config.username.strip().casefold()
    expected_username = username.strip().casefold()
    return configured_server == expected_server and configured_username == expected_username


def config_path() -> Path:
    configured_path = os.environ.get("ABS_KIDS_PLAYER_CONFIG_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()

    configured_dir = os.environ.get("ABS_KIDS_PLAYER_CONFIG_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / "config.json"

    return CONFIG_PATH


def valid_screen_saver_mode(value: str) -> str:
    return value if value in SCREEN_SAVER_MODES else SCREEN_SAVER_CHAPTER


def valid_library_sort_mode(value: str) -> str:
    return value if value in LIBRARY_SORT_MODES else LIBRARY_SORT_TITLE


def valid_screen_saver_dim_percent(value: object) -> int:
    try:
        percent = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SCREEN_SAVER_DIM_PERCENT
    return percent if percent in SCREEN_SAVER_DIM_LEVELS else DEFAULT_SCREEN_SAVER_DIM_PERCENT


def valid_sleep_timer_minutes(value: object) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SLEEP_TIMER_MINUTES
    return min(max(minutes, MIN_SLEEP_TIMER_MINUTES), MAX_SLEEP_TIMER_MINUTES)


def podcast_configs_from_json(value: object) -> list[PodcastConfig]:
    if not isinstance(value, list):
        return default_podcasts()

    podcasts: list[PodcastConfig] = []
    for item in value:
        if isinstance(item, str):
            url = item.strip()
            if url:
                podcasts.append(PodcastConfig(url=url))
            continue
        if not isinstance(item, dict):
            continue
        podcast = PodcastConfig(
            url=str(item.get("url", "")).strip(),
            title=str(item.get("title", "")).strip(),
            author=str(item.get("author", "")).strip(),
            feed_url=str(item.get("feed_url", "")).strip(),
            book_id=str(item.get("book_id", "")).strip(),
        )
        if podcast.url or podcast.feed_url:
            podcasts.append(podcast)
    return podcasts
