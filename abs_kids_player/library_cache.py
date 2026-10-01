from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from .config import AppConfig
from .models import Book
from .storage import ensure_storage_directory, finalize_storage_file


LIBRARY_CACHE_PATH = Path.home() / ".local" / "state" / "abs-kids-player" / "library-cache.json"
LIBRARY_CACHE_VERSION = 1


def load_cached_books(config: AppConfig) -> list[Book]:
    if not config.is_ready:
        return []

    try:
        payload = json.loads(library_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []
    if payload.get("version") != LIBRARY_CACHE_VERSION:
        return []
    if payload.get("config_key") != config_cache_key(config):
        return []

    books: list[Book] = []
    for value in payload.get("books", []):
        if not isinstance(value, dict):
            continue
        try:
            books.append(
                Book(
                    id=str(value["id"]),
                    title=str(value["title"]),
                    author=str(value.get("author", "")),
                    duration=float(value.get("duration", 0)),
                    cover_url="",
                    current_time=float(value.get("current_time", 0)),
                    progress=float(value.get("progress", 0)),
                    series_name=str(value.get("series_name", "")),
                    series_sequence=str(value.get("series_sequence", "")),
                    series_total=int(value.get("series_total", 0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return books


def save_cached_books(config: AppConfig, books: list[Book]) -> None:
    if not config.is_ready:
        return

    path = library_cache_path()
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "version": LIBRARY_CACHE_VERSION,
        "config_key": config_cache_key(config),
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "duration": book.duration,
                "current_time": book.current_time,
                "progress": book.progress,
                "series_name": book.series_name,
                "series_sequence": book.series_sequence,
                "series_total": book.series_total,
            }
            for book in books
        ],
    }
    try:
        ensure_storage_directory(path.parent)
        temporary_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        finalize_storage_file(temporary_path)
        temporary_path.replace(path)
        finalize_storage_file(path)
    except OSError as error:
        print(f"Library cache could not be saved: {error}")


def clear_cached_books() -> None:
    try:
        library_cache_path().unlink(missing_ok=True)
    except OSError:
        pass


def config_cache_key(config: AppConfig) -> str:
    identity = {
        "server_url": config.server_url.rstrip("/"),
        "library_id": config.library_id,
        "username": config.username,
        "podcasts": [asdict(podcast) for podcast in config.podcasts],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def library_cache_path() -> Path:
    configured_path = os.environ.get("ABS_KIDS_PLAYER_LIBRARY_CACHE_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    configured_dir = os.environ.get("ABS_KIDS_PLAYER_STATE_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser() / LIBRARY_CACHE_PATH.name
    return LIBRARY_CACHE_PATH
