from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Book:
    id: str
    title: str
    author: str
    duration: float
    cover_url: str
    current_time: float = 0
    progress: float = 0
    series_name: str = ""
    series_sequence: str = ""
    series_total: int = 0

    @property
    def has_play_history(self) -> bool:
        return self.current_time >= 5 and self.progress < 0.995

    @property
    def display_title(self) -> str:
        title = self.title.strip()
        series = self.series_name.strip()
        if not series:
            return title
        prefix = f"{series}:"
        if title.casefold().startswith(prefix.casefold()):
            return title
        return f"{series}: {title}"

    @property
    def series_position(self) -> str:
        if not self.series_sequence or self.series_total < 2:
            return ""
        return f"{self.series_sequence}/{self.series_total}"


@dataclass
class AudioTrack:
    index: int
    start_offset: float
    duration: float
    url: str
    title: str


@dataclass
class Chapter:
    index: int
    title: str
    start: float
    end: float


@dataclass
class PlaybackSession:
    id: str
    library_item_id: str
    title: str
    author: str
    duration: float
    current_time: float
    cover_url: str
    tracks: list[AudioTrack]
    chapters: list[Chapter]
