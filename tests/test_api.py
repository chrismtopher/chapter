from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from abs_kids_player import __version__
from abs_kids_player.api import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    AudiobookshelfClient,
    AudiobookshelfError,
    author_from_metadata,
    clean_author,
    normalized_series_sequence,
    primary_series_from_metadata,
)


class FakePlaybackClient(AudiobookshelfClient):
    def __init__(self, progress_time: float = 42.0) -> None:
        super().__init__("https://books.example.com", "token")
        self.progress_time = progress_time
        self.calls: list[tuple[str, str]] = []
        self.last_playback_body = None

    def get_progress(self, item_id: str) -> dict[str, float]:
        self.calls.append(("GET_PROGRESS", item_id))
        return {"currentTime": self.progress_time, "progress": self.progress_time / 300}

    def request(self, method: str, path: str, body=None, query=None):
        self.calls.append((method, path))
        if method == "POST" and path == "/api/items/book-1/play":
            self.last_playback_body = body
            return {
                "id": "play-1",
                "duration": 300,
                "currentTime": 0,
                "mediaMetadata": {"title": "The Hobbit", "authorName": "J.R.R. Tolkien"},
                "audioTracks": [
                    {
                        "index": 1,
                        "startOffset": 0,
                        "duration": 300,
                        "contentUrl": "/audiobooks/book-1.mp3",
                        "title": "Track 1",
                    }
                ],
            }
        raise AssertionError(f"Unexpected request: {method} {path}")


class FakeProgressClient(AudiobookshelfClient):
    def __init__(self, fail_session_sync: bool = False, fail_progress_patch: bool = False) -> None:
        super().__init__("https://books.example.com", "token")
        self.fail_session_sync = fail_session_sync
        self.fail_progress_patch = fail_progress_patch
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, path: str, body=None, query=None):
        self.calls.append((method, path, body or {}))
        if path.endswith("/sync") and self.fail_session_sync:
            raise AudiobookshelfError("session unavailable")
        if path.startswith("/api/me/progress/") and self.fail_progress_patch:
            raise AudiobookshelfError("progress unavailable")
        return {}


class ApiMetadataTest(unittest.TestCase):
    @staticmethod
    def json_response(payload: dict) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
        return response

    def test_login_prefers_jwt_tokens_and_requests_mobile_token_response(self) -> None:
        response = self.json_response(
            {
                "user": {
                    "username": "chapter",
                    "token": "legacy-token",
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                }
            }
        )

        with patch("abs_kids_player.api.urlopen", return_value=response) as urlopen:
            client, _data = AudiobookshelfClient.login(
                "https://books.example.com",
                "chapter",
                "secret",
            )

        request = urlopen.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-return-tokens"], "true")
        self.assertEqual(client.token, "access-token")
        self.assertEqual(client.refresh_token, "refresh-token")

    def test_login_keeps_legacy_server_compatibility(self) -> None:
        response = self.json_response({"user": {"username": "chapter", "token": "legacy-token"}})

        with patch("abs_kids_player.api.urlopen", return_value=response):
            client, _data = AudiobookshelfClient.login(
                "https://books.example.com",
                "chapter",
                "secret",
            )

        self.assertEqual(client.token, "legacy-token")
        self.assertEqual(client.refresh_token, "")

    def test_request_refreshes_rotated_tokens_and_retries_after_401(self) -> None:
        unauthorized = HTTPError(
            "https://books.example.com/api/me",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"expired"}'),
        )
        refresh_response = self.json_response(
            {"user": {"accessToken": "new-access", "refreshToken": "new-refresh"}}
        )
        api_response = self.json_response({"username": "chapter"})
        saved_tokens: list[tuple[str, str]] = []
        client = AudiobookshelfClient(
            "https://books.example.com",
            "expired-access",
            refresh_token="old-refresh",
            token_saver=lambda access, refresh: saved_tokens.append((access, refresh)),
        )

        with patch(
            "abs_kids_player.api.urlopen",
            side_effect=[unauthorized, refresh_response, api_response],
        ) as urlopen:
            data = client.request("GET", "/api/me")

        refresh_request = urlopen.call_args_list[1].args[0]
        retry_request = urlopen.call_args_list[2].args[0]
        refresh_headers = {key.lower(): value for key, value in refresh_request.header_items()}
        retry_headers = {key.lower(): value for key, value in retry_request.header_items()}
        self.assertEqual(data, {"username": "chapter"})
        self.assertEqual(refresh_request.full_url, "https://books.example.com/auth/refresh")
        self.assertEqual(refresh_headers["x-refresh-token"], "old-refresh")
        self.assertEqual(retry_headers["authorization"], "Bearer new-access")
        self.assertEqual(saved_tokens, [("new-access", "new-refresh")])

    def test_primary_series_reads_modern_audiobookshelf_metadata(self) -> None:
        series = primary_series_from_metadata(
            {
                "series": [
                    {"id": "series-1", "name": "The Wild Robot", "sequence": "02.0"},
                ]
            }
        )

        self.assertEqual(series, ("The Wild Robot", "2"))

    def test_primary_series_reads_legacy_series_name(self) -> None:
        series = primary_series_from_metadata(
            {"seriesName": "Harry Potter (Full-Cast Editions) #5"}
        )

        self.assertEqual(series, ("Harry Potter (Full-Cast Editions)", "5"))

    def test_normalized_series_sequence_rejects_non_numeric_values(self) -> None:
        self.assertEqual(normalized_series_sequence("Book One"), "")

    def test_get_books_uses_audiobookshelf_series_total(self) -> None:
        client = AudiobookshelfClient("https://books.example.com", "token")
        item = {
            "id": "book-1",
            "mediaProgress": {"currentTime": 10, "progress": 0.1},
            "media": {
                "duration": 100,
                "metadata": {
                    "title": "The Wild Robot Escapes",
                    "authorName": "Peter Brown",
                    "series": [{"name": "The Wild Robot", "sequence": "2"}],
                },
            },
        }
        with patch.object(
            client,
            "request",
            side_effect=[
                {"results": [{"name": "The Wild Robot", "numBooks": 3}]},
                {"results": [item]},
            ],
        ):
            books = client.get_books("library-1")

        self.assertEqual(books[0].series_name, "The Wild Robot")
        self.assertEqual(books[0].display_title, "The Wild Robot: The Wild Robot Escapes")
        self.assertEqual(books[0].series_position, "2/3")

    def test_get_books_uses_highest_legacy_sequence_when_series_endpoint_is_empty(self) -> None:
        client = AudiobookshelfClient("https://books.example.com", "token")

        def item(book_id: str, sequence: int) -> dict:
            return {
                "id": book_id,
                "mediaProgress": {"currentTime": 10, "progress": 0.1},
                "media": {
                    "duration": 100,
                    "metadata": {
                        "title": f"Harry Potter {sequence}",
                        "seriesName": f"Harry Potter #{sequence}",
                    },
                },
            }

        with patch.object(
            client,
            "request",
            side_effect=[
                {"results": []},
                {"results": [item("book-2", 2), item("book-7", 7)]},
            ],
        ):
            books = client.get_books("library-1")

        self.assertEqual([book.series_position for book in books], ["2/7", "7/7"])

    def test_request_converts_socket_timeout_to_audiobookshelf_error(self) -> None:
        client = AudiobookshelfClient("https://books.example.com", "token")

        with patch("abs_kids_player.api.urlopen", side_effect=TimeoutError("timed out")) as urlopen:
            with self.assertRaises(AudiobookshelfError) as error:
                client.request("GET", "/api/me")

        self.assertIn("timed out", str(error.exception))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], DEFAULT_REQUEST_TIMEOUT_SECONDS)

    def test_login_converts_socket_timeout_to_audiobookshelf_error(self) -> None:
        with patch("abs_kids_player.api.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(AudiobookshelfError) as error:
                AudiobookshelfClient.login("https://books.example.com", "chapter", "secret")

        self.assertIn("timed out", str(error.exception))

    def test_start_playback_uses_saved_progress_before_opening_session(self) -> None:
        client = FakePlaybackClient()

        session = client.start_playback("book-1", start_over=False)

        self.assertEqual(client.calls[:2], [("GET_PROGRESS", "book-1"), ("POST", "/api/items/book-1/play")])
        self.assertEqual(session.current_time, 42.0)
        self.assertEqual(client.last_playback_body["deviceInfo"]["clientVersion"], __version__)

    def test_start_over_ignores_saved_progress(self) -> None:
        client = FakePlaybackClient()

        session = client.start_playback("book-1", start_over=True)

        self.assertEqual(client.calls[:1], [("POST", "/api/items/book-1/play")])
        self.assertEqual(session.current_time, 0)

    def test_start_playback_falls_back_to_resume_time_from_book_list(self) -> None:
        client = FakePlaybackClient(progress_time=0)

        session = client.start_playback("book-1", start_over=False, resume_time=67.0)

        self.assertEqual(session.current_time, 67.0)

    def test_update_progress_syncs_open_session_and_media_progress(self) -> None:
        client = FakeProgressClient()

        client.update_progress("book-1", current_time=42, duration=300, session_id="play-1", time_listened=15)

        self.assertEqual(client.calls[0][0:2], ("POST", "/api/session/play-1/sync"))
        self.assertEqual(client.calls[0][2]["currentTime"], 42)
        self.assertEqual(client.calls[0][2]["timeListened"], 15)
        self.assertEqual(client.calls[1][0:2], ("PATCH", "/api/me/progress/book-1"))
        self.assertEqual(client.calls[1][2]["currentTime"], 42)

    def test_update_progress_still_patches_when_open_session_sync_fails(self) -> None:
        client = FakeProgressClient(fail_session_sync=True)

        client.update_progress("book-1", current_time=42, duration=300, session_id="play-1", time_listened=15)

        self.assertEqual(client.calls[0][0:2], ("POST", "/api/session/play-1/sync"))
        self.assertEqual(client.calls[1][0:2], ("PATCH", "/api/me/progress/book-1"))

    def test_author_from_metadata_ignores_narrator_field(self) -> None:
        author = author_from_metadata(
            {
                "authorName": "Roald Dahl",
                "narratorName": "Kate Winslet",
            }
        )

        self.assertEqual(author, "Roald Dahl")

    def test_clean_author_strips_narrated_by_suffix(self) -> None:
        self.assertEqual(clean_author("Roald Dahl narrated by Kate Winslet"), "Roald Dahl")
        self.assertEqual(clean_author("Roald Dahl - Narrator: Kate Winslet"), "Roald Dahl")
        self.assertEqual(clean_author("Roald Dahl / read by Kate Winslet"), "Roald Dahl")

    def test_author_from_metadata_falls_back_to_author(self) -> None:
        self.assertEqual(author_from_metadata({"author": "Beverly Cleary"}), "Beverly Cleary")

    def test_author_from_metadata_prefers_written_by_author_string(self) -> None:
        author = author_from_metadata(
            {
                "authors": [
                    "Narrated By: Kate Winslet",
                    "Written By: Roald Dahl",
                ],
                "authorName": "Kate Winslet",
            }
        )

        self.assertEqual(author, "Roald Dahl")

    def test_author_from_metadata_prefers_written_by_author_object(self) -> None:
        author = author_from_metadata(
            {
                "authors": [
                    {"role": "Narrated By", "name": "Kate Winslet"},
                    {"role": "Written By", "name": "Roald Dahl"},
                ],
            }
        )

        self.assertEqual(author, "Roald Dahl")


if __name__ == "__main__":
    unittest.main()
