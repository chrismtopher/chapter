from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from abs_kids_player.podcast import (
    PODCAST_REQUEST_HEADERS,
    TRIVIA_FOR_KIDS_BOOK_ID,
    YOTO_DAILY_FALLBACK_FEED_URL,
    latest_episode,
    parse_duration,
    podcast_book_id,
    resolve_podcast_config,
    resolve_yoto_daily_feed_url,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class PodcastTest(unittest.TestCase):
    def test_resolve_yoto_daily_feed_url_uses_apple_lookup_feed_url(self) -> None:
        payload = json.dumps({"results": [{"feedUrl": "https://feeds.example.com/yoto.xml"}]}).encode()

        with patch("abs_kids_player.podcast.urlopen", return_value=FakeResponse(payload)):
            self.assertEqual(resolve_yoto_daily_feed_url(), "https://feeds.example.com/yoto.xml")

    def test_resolve_yoto_daily_feed_url_falls_back_when_lookup_has_no_feed(self) -> None:
        payload = json.dumps({"results": [{}]}).encode()

        with patch("abs_kids_player.podcast.urlopen", return_value=FakeResponse(payload)):
            self.assertEqual(resolve_yoto_daily_feed_url(), YOTO_DAILY_FALLBACK_FEED_URL)

    def test_resolve_podcast_config_accepts_apple_podcast_link(self) -> None:
        payload = json.dumps(
            {
                "results": [
                    {
                        "collectionName": "Trivia for Kids",
                        "artistName": "KRCreative",
                        "feedUrl": "https://feeds.example.com/trivia.xml",
                    }
                ]
            }
        ).encode()

        with patch("abs_kids_player.podcast.urlopen", return_value=FakeResponse(payload)):
            podcast = resolve_podcast_config("http://podcasts.apple.com/us/podcast/trivia-for-kids/id1603986433")

        self.assertEqual(podcast.title, "Trivia for Kids")
        self.assertEqual(podcast.author, "KRCreative")
        self.assertEqual(podcast.feed_url, "https://feeds.example.com/trivia.xml")
        self.assertEqual(podcast.book_id, TRIVIA_FOR_KIDS_BOOK_ID)

    def test_resolve_podcast_config_accepts_direct_rss_feed(self) -> None:
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
          <channel>
            <title>Bedtime Stories</title>
            <itunes:author>Story Parent</itunes:author>
          </channel>
        </rss>"""

        with patch("abs_kids_player.podcast.urlopen", return_value=FakeResponse(rss)):
            podcast = resolve_podcast_config("https://feeds.example.com/bedtime.xml")

        self.assertEqual(podcast.title, "Bedtime Stories")
        self.assertEqual(podcast.author, "Story Parent")
        self.assertEqual(podcast.feed_url, "https://feeds.example.com/bedtime.xml")
        self.assertEqual(podcast.book_id, podcast_book_id("https://feeds.example.com/bedtime.xml"))

    def test_latest_episode_reads_first_rss_item_enclosure(self) -> None:
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
          <channel>
            <item>
              <title>Draw-Along with Jake</title>
              <guid>episode-1</guid>
              <itunes:duration>16:53</itunes:duration>
              <itunes:image href="https://example.com/cover.jpg" />
              <enclosure url="https://example.com/yoto.mp3" type="audio/mpeg" />
            </item>
          </channel>
        </rss>"""

        with patch("abs_kids_player.podcast.urlopen", return_value=FakeResponse(rss)):
            episode = latest_episode("https://feeds.example.com/yoto.xml")

        self.assertEqual(episode.title, "Draw-Along with Jake")
        self.assertEqual(episode.guid, "episode-1")
        self.assertEqual(episode.audio_url, "https://example.com/yoto.mp3")
        self.assertEqual(episode.cover_url, "https://example.com/cover.jpg")
        self.assertEqual(episode.duration, 1013)

    def test_latest_episode_uses_podcast_request_headers(self) -> None:
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item><title>Episode</title><enclosure url="https://example.com/audio.mp3" /></item></channel></rss>"""

        with patch("abs_kids_player.podcast.urlopen", return_value=FakeResponse(rss)) as open_url:
            latest_episode("https://feeds.example.com/show.xml")

        request = open_url.call_args.args[0]

        self.assertEqual(request.headers["User-agent"], PODCAST_REQUEST_HEADERS["User-Agent"])
        self.assertIn("application/rss+xml", request.headers["Accept"])

    def test_parse_duration_accepts_common_podcast_formats(self) -> None:
        self.assertEqual(parse_duration("16:53"), 1013)
        self.assertEqual(parse_duration("1:02:03"), 3723)
        self.assertEqual(parse_duration("72"), 72)
        self.assertEqual(parse_duration("1h 2m 3s"), 3723)


if __name__ == "__main__":
    unittest.main()
