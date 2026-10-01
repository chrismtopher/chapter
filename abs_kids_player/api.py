from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from .models import AudioTrack, Book, Chapter, PlaybackSession


SUPPORTED_MIME_TYPES = [
    "audio/aac",
    "audio/flac",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
]
DEFAULT_REQUEST_TIMEOUT_SECONDS = 8


class AudiobookshelfError(RuntimeError):
    pass


class AudiobookshelfClient:
    def __init__(self, server_url: str, token: str) -> None:
        self.server_url = server_url.rstrip("/") + "/"
        self.token = token

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = urljoin(self.server_url, path.lstrip("/"))
        if query:
            return f"{url}?{urlencode(query)}"
        return url

    def authenticated_media_url(self, path: str) -> str:
        parsed = urlparse(urljoin(self.server_url, path.lstrip("/")))
        query = urlencode({"token": self.token})
        if parsed.query:
            query = parsed.query + "&" + query
        return urlunparse(parsed._replace(query=query))

    @classmethod
    def login(cls, server_url: str, username: str, password: str) -> tuple["AudiobookshelfClient", dict[str, Any]]:
        server_url = server_url.rstrip("/") + "/"
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        request = Request(
            urljoin(server_url, "login"),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise AudiobookshelfError(f"Audiobookshelf login failed with {error.code}: {details}") from error
        except TimeoutError as error:
            raise AudiobookshelfError("Audiobookshelf request timed out.") from error
        except URLError as error:
            raise AudiobookshelfError(f"Could not reach Audiobookshelf: {error.reason}") from error

        token = extract_login_token(data)
        if not token:
            raise AudiobookshelfError("Audiobookshelf login did not return a user token.")
        return cls(server_url, token), data

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | list[Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {"Authorization": f"Bearer {self.token}"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self._url(path, query), data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS) as response:
                payload = response.read()
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise AudiobookshelfError(f"Audiobookshelf returned {error.code}: {details}") from error
        except TimeoutError as error:
            raise AudiobookshelfError("Audiobookshelf request timed out.") from error
        except URLError as error:
            raise AudiobookshelfError(f"Could not reach Audiobookshelf: {error.reason}") from error

        if not payload:
            return None

        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            return payload

    def get_libraries(self) -> list[dict[str, Any]]:
        data = self.request("GET", "/api/libraries")
        if isinstance(data, list):
            return list(data)
        return list(data.get("libraries", []))

    def choose_library_id(self, configured_id: str = "") -> str:
        if configured_id:
            return configured_id

        libraries = self.get_libraries()
        for library in libraries:
            if library.get("mediaType") == "book":
                return str(library["id"])
        if libraries:
            return str(libraries[0]["id"])
        raise AudiobookshelfError("No accessible libraries were found for this token.")

    def get_current_user(self) -> dict[str, Any]:
        data = self.request("GET", "/api/me")
        if isinstance(data, dict):
            return data
        raise AudiobookshelfError("Audiobookshelf did not return current user details.")

    def get_books(self, library_id: str) -> list[Book]:
        series_totals = self.get_series_totals(library_id)
        data = self.request(
            "GET",
            f"/api/libraries/{library_id}/items",
            query={"sort": "media.metadata.title", "minified": 0},
        )
        books: list[Book] = []
        series_keys: list[str] = []
        fallback_counts: dict[str, int] = {}
        fallback_highest_sequences: dict[str, int] = {}
        for item in data.get("results", []):
            media = item.get("media") or {}
            metadata = media.get("metadata") or {}
            title = metadata.get("title") or item.get("relPath") or "Untitled"
            author = author_from_metadata(metadata)
            cover_url = self.authenticated_media_url(f"/api/items/{item['id']}/cover")
            progress = extract_progress(item)
            series_name, series_sequence = primary_series_from_metadata(metadata)
            series_key = series_name.casefold()
            book = Book(
                id=str(item["id"]),
                title=str(title),
                author=str(author),
                duration=float(media.get("duration") or 0),
                cover_url=cover_url,
                current_time=float(progress.get("currentTime") or 0),
                progress=float(progress.get("progress") or 0),
                series_name=series_name,
                series_sequence=series_sequence,
            )
            if not book.current_time:
                remote_progress = self.get_progress(book.id) or {}
                book.current_time = float(remote_progress.get("currentTime") or 0)
                book.progress = float(remote_progress.get("progress") or 0)
            books.append(book)
            series_keys.append(series_key)
            if series_key:
                fallback_counts[series_key] = fallback_counts.get(series_key, 0) + 1
                if series_sequence:
                    sequence_ceiling = math.ceil(float(series_sequence))
                    fallback_highest_sequences[series_key] = max(
                        fallback_highest_sequences.get(series_key, 0),
                        sequence_ceiling,
                    )

        for book, series_key in zip(books, series_keys):
            if not series_key:
                continue
            book.series_total = series_totals.get(
                series_key,
                max(
                    fallback_counts.get(series_key, 0),
                    fallback_highest_sequences.get(series_key, 0),
                ),
            )
        return books

    def get_series_totals(self, library_id: str) -> dict[str, int]:
        try:
            data = self.request(
                "GET",
                f"/api/libraries/{library_id}/series",
                query={"limit": 0},
            )
        except AudiobookshelfError:
            return {}

        rows = data.get("results", []) if isinstance(data, dict) else data
        totals: dict[str, int] = {}
        for series in rows or []:
            if not isinstance(series, dict):
                continue
            name = str(series.get("name") or "").strip()
            try:
                total = int(series.get("numBooks") or 0)
            except (TypeError, ValueError):
                total = 0
            if name and total > 0:
                totals[name.casefold()] = total
        return totals

    def get_progress(self, item_id: str) -> dict[str, Any] | None:
        try:
            return self.request("GET", f"/api/me/progress/{item_id}")
        except AudiobookshelfError as error:
            if "404" in str(error):
                return None
            raise

    def start_playback(self, item_id: str, start_over: bool = False, resume_time: float = 0) -> PlaybackSession:
        saved_progress = {} if start_over else self.get_progress(item_id) or {}
        session = self.request(
            "POST",
            f"/api/items/{item_id}/play",
            body={
                "deviceInfo": {
                    "clientName": "ABS Kids Player",
                    "clientVersion": "0.1.0",
                    "manufacturer": "Raspberry Pi",
                    "model": "Ubuntu",
                },
                "mediaPlayer": "gstreamer",
                "supportedMimeTypes": SUPPORTED_MIME_TYPES,
            },
        )
        current_time = 0 if start_over else progress_current_time(saved_progress, {"currentTime": resume_time}, session)
        cover_path = session.get("coverPath") or f"/api/items/{item_id}/cover"
        tracks = [
            AudioTrack(
                index=int(track.get("index") or index + 1),
                start_offset=float(track.get("startOffset") or 0),
                duration=float(track.get("duration") or 0),
                url=self.authenticated_media_url(str(track["contentUrl"])),
                title=str(track.get("title") or ""),
            )
            for index, track in enumerate(session.get("audioTracks") or [])
            if track.get("contentUrl")
        ]
        if not tracks:
            raise AudiobookshelfError("This item did not include playable audio tracks.")

        chapters = parse_chapters(session.get("chapters") or [], session.get("duration") or 0)
        if not chapters:
            chapters = [
                Chapter(
                    index=track.index,
                    title=track.title or f"Track {track.index}",
                    start=track.start_offset,
                    end=track.start_offset + track.duration,
                )
                for track in tracks
            ]

        metadata = session.get("mediaMetadata") or {}
        author = author_from_metadata(metadata) or clean_author(session.get("displayAuthor") or "")

        return PlaybackSession(
            id=str(session["id"]),
            library_item_id=item_id,
            title=str(session.get("displayTitle") or session.get("mediaMetadata", {}).get("title") or "Untitled"),
            author=author,
            duration=float(session.get("duration") or 0),
            current_time=current_time,
            cover_url=self.authenticated_media_url(str(cover_path)),
            tracks=tracks,
            chapters=chapters,
        )

    def sync_session_progress(
        self,
        session_id: str,
        current_time: float,
        duration: float,
        time_listened: float = 0,
    ) -> None:
        self.request(
            "POST",
            f"/api/session/{session_id}/sync",
            body={
                "currentTime": current_time,
                "timeListened": max(0.0, time_listened),
                "duration": duration,
            },
        )

    def update_progress(
        self,
        item_id: str,
        current_time: float,
        duration: float,
        session_id: str = "",
        time_listened: float = 0,
    ) -> None:
        progress = min(max(current_time / duration, 0), 1) if duration else 0
        errors: list[AudiobookshelfError] = []
        synced = False

        if session_id:
            try:
                self.sync_session_progress(session_id, current_time, duration, time_listened)
                synced = True
            except AudiobookshelfError as error:
                errors.append(error)

        try:
            self.request(
                "PATCH",
                f"/api/me/progress/{item_id}",
                body={
                    "duration": duration,
                    "progress": progress,
                    "currentTime": current_time,
                    "isFinished": bool(duration and progress >= 0.995),
                },
            )
            synced = True
        except AudiobookshelfError as error:
            errors.append(error)

        if not synced and errors:
            raise errors[0]


def primary_series_from_metadata(metadata: dict[str, Any]) -> tuple[str, str]:
    raw_series = metadata.get("series") or []
    if isinstance(raw_series, dict):
        raw_series = [raw_series]

    entries: list[tuple[str, str]] = []
    if isinstance(raw_series, list):
        for value in raw_series:
            if not isinstance(value, dict):
                continue
            name = str(value.get("name") or value.get("series") or "").strip()
            if name:
                entries.append((name, normalized_series_sequence(value.get("sequence"))))

    for entry in entries:
        if entry[1]:
            return entry
    if entries:
        return entries[0]

    legacy = str(metadata.get("seriesName") or "").strip()
    match = re.match(r"^(.*?)\s+#\s*(\d+(?:\.\d+)?)\s*$", legacy)
    if match:
        return match.group(1).strip(), normalized_series_sequence(match.group(2))
    return (legacy, "") if legacy else ("", "")


def normalized_series_sequence(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return ""
    whole, separator, fraction = text.partition(".")
    normalized_whole = str(int(whole))
    normalized_fraction = fraction.rstrip("0")
    if separator and normalized_fraction:
        return f"{normalized_whole}.{normalized_fraction}"
    return normalized_whole


def parse_chapters(raw_chapters: list[dict[str, Any]], duration: float) -> list[Chapter]:
    chapters: list[Chapter] = []
    for index, chapter in enumerate(raw_chapters):
        start = float(chapter.get("start") or chapter.get("startTime") or 0)
        end = float(chapter.get("end") or chapter.get("endTime") or duration or 0)
        try:
            chapter_index = int(chapter.get("index") or chapter.get("id") or index + 1)
        except (TypeError, ValueError):
            chapter_index = index + 1
        chapters.append(
            Chapter(
                index=chapter_index,
                title=str(chapter.get("title") or f"Chapter {index + 1}"),
                start=start,
                end=end,
            )
        )
    return chapters


def extract_progress(item: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        item.get("mediaProgress"),
        item.get("userMediaProgress"),
        item.get("progress"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def progress_current_time(*sources: dict[str, Any]) -> float:
    fallback = 0.0
    for source in sources:
        for key in ("currentTime", "current_time"):
            value = source.get(key)
            if value not in (None, ""):
                current_time = float(value)
                if current_time > 0:
                    return current_time
                fallback = current_time
        progress = extract_progress(source)
        value = progress.get("currentTime")
        if value not in (None, ""):
            current_time = float(value)
            if current_time > 0:
                return current_time
            fallback = current_time
    return fallback


def author_from_metadata(metadata: dict[str, Any]) -> str:
    written_by = written_by_author(metadata.get("authors"))
    if written_by:
        return written_by
    written_by = written_by_author(metadata.get("authorName") or metadata.get("author"))
    if written_by:
        return written_by
    return clean_author(metadata.get("authorName") or metadata.get("author") or "")


def written_by_author(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            author = written_by_author(item)
            if author:
                return author
        return ""

    if isinstance(value, dict):
        role = str(value.get("role") or value.get("type") or value.get("label") or "").strip()
        name = value.get("name") or value.get("authorName") or value.get("author") or value.get("value") or ""
        if role.lower().startswith("written by"):
            return clean_author(name)
        return written_by_author(name)

    text = str(value or "").strip()
    match = re.match(r"^written\s+by\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if match:
        return clean_author(match.group(1))
    return ""


def clean_author(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(clean_author(item) for item in value if clean_author(item))
    elif isinstance(value, dict):
        value = value.get("name") or value.get("authorName") or value.get("author") or ""
    text = str(value or "").strip()
    if not text:
        return ""

    text = re.split(r"\s+(?:narrated by|narrator:?|read by)\s+", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"\s+[-|/]\s+(?:narrated by|narrator:?|read by)\s*", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return text.strip(" -|/")


def extract_login_token(data: dict[str, Any]) -> str:
    user = data.get("user") or {}
    candidates = [
        user.get("token"),
        user.get("accessToken"),
        user.get("access_token"),
        data.get("token"),
        data.get("accessToken"),
        data.get("access_token"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""
