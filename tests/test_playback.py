from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from abs_kids_player.playback import (
    GStreamerPlayback,
    SILENCE_VOLUME_FLOOR,
    SPOKEN_NAVIGATION_DUCK_FACTOR,
    smart_resume_rewind_seconds,
)


class FakePlaybin:
    def __init__(self, reject_mute: bool = False) -> None:
        self.reject_mute = reject_mute
        self.properties: dict[str, object] = {}
        self.volume_values: list[float] = []
        self.states: list[object] = []
        self.seeks: list[tuple[object, object, int]] = []
        self.events: list[tuple[str, object]] = []
        self.position = 0
        self.query_position_calls = 0

    def set_property(self, name: str, value: object) -> None:
        if name == "mute" and self.reject_mute:
            raise TypeError("unknown property mute")
        self.properties[name] = value
        if name == "volume":
            self.volume_values.append(float(value))
            self.events.append(("volume", float(value)))

    def set_state(self, state: object) -> None:
        self.states.append(state)
        self.events.append(("state", state))

    def get_state(self, _timeout: int) -> tuple[None, None, None]:
        self.events.append(("get_state", _timeout))
        return None, None, None

    def query_position(self, _format: object) -> tuple[bool, int]:
        self.query_position_calls += 1
        return True, self.position

    def seek_simple(self, format_: object, flags: object, position: int) -> None:
        self.seeks.append((format_, flags, position))
        self.events.append(("seek", position))


class FakeSink:
    def __init__(self) -> None:
        self.properties: dict[str, object] = {}

    def set_property(self, name: str, value: object) -> None:
        self.properties[name] = value


class FakeGst:
    SECOND = 1

    class ElementFactory:
        @staticmethod
        def make(_element_type: str, _name: str) -> FakePlaybin:
            return FakePlaybin()

    class State:
        NULL = "null"
        PAUSED = "paused"
        PLAYING = "playing"

    class Format:
        TIME = "time"

    class SeekFlags:
        FLUSH = 1
        KEY_UNIT = 2
        ACCURATE = 4


class FakeGstWithSink(FakeGst):
    sinks: list[FakeSink] = []

    class ElementFactory:
        @staticmethod
        def make(element_type: str, _name: str):
            if element_type == "alsasink":
                sink = FakeSink()
                FakeGstWithSink.sinks.append(sink)
                return sink
            return FakePlaybin()


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, float, str, float]] = []

    def update_progress(
        self,
        item_id: str,
        current_time: float,
        duration: float,
        session_id: str = "",
        time_listened: float = 0,
    ) -> None:
        self.calls.append((item_id, current_time, duration, session_id, time_listened))


class PlaybackTest(unittest.TestCase):
    def test_start_sets_volume_floor_before_preroll(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        session = SimpleNamespace(
            library_item_id="book-1",
            duration=300,
            current_time=42,
            tracks=[SimpleNamespace(start_offset=0, duration=300, url="http://example.test/book.mp3")],
        )

        with patch("abs_kids_player.playback.load_gstreamer", return_value=FakeGst()):
            with patch("abs_kids_player.playback.time.sleep"):
                playback.start(session, FakeClient())

        self.assertAlmostEqual(playback.playbin.volume_values[0], SILENCE_VOLUME_FLOOR)
        self.assertEqual(playback.playbin.states[0], FakeGst.State.NULL)
        self.assertEqual(playback.playbin.states[-1], FakeGst.State.PLAYING)
        self.assertEqual(playback.playbin.seeks[-1], (FakeGst.Format.TIME, 3, 42))
        playing_index = playback.playbin.events.index(("state", FakeGst.State.PLAYING))
        preroll_seek_index = playback.playbin.events.index(("seek", 42))
        first_audible_volume_index = next(
            index
            for index, event in enumerate(playback.playbin.events)
            if event[0] == "volume" and event[1] > SILENCE_VOLUME_FLOOR
        )
        self.assertLess(preroll_seek_index, playing_index)
        self.assertLess(playing_index, first_audible_volume_index)

    def test_start_uses_bluetooth_alsa_sink_when_connected(self) -> None:
        playback = GStreamerPlayback()
        playback.set_bluetooth_output_enabled(True)
        session = SimpleNamespace(
            library_item_id="book-1",
            duration=300,
            current_time=42,
            tracks=[SimpleNamespace(start_offset=0, duration=300, url="http://example.test/book.mp3")],
        )
        FakeGstWithSink.sinks = []
        device = "bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp"

        with patch("abs_kids_player.playback.load_gstreamer", return_value=FakeGstWithSink()):
            with patch("abs_kids_player.playback.preferred_bluetooth_alsa_device", return_value=device):
                with patch("abs_kids_player.playback.time.sleep"):
                    playback.start(session, FakeClient())

        self.assertEqual(playback.audio_output_device, device)
        self.assertEqual(len(FakeGstWithSink.sinks), 1)
        self.assertEqual(FakeGstWithSink.sinks[0].properties["device"], device)
        self.assertIs(playback.playbin.properties["audio-sink"], FakeGstWithSink.sinks[0])

    def test_start_uses_internal_speaker_without_probing_bluetooth(self) -> None:
        playback = GStreamerPlayback()
        session = SimpleNamespace(
            library_item_id="book-1",
            duration=300,
            current_time=42,
            tracks=[SimpleNamespace(start_offset=0, duration=300, url="http://example.test/book.mp3")],
        )

        with patch("abs_kids_player.playback.load_gstreamer", return_value=FakeGst()):
            with patch("abs_kids_player.playback.preferred_bluetooth_alsa_device") as bluetooth_device:
                with patch("abs_kids_player.playback.time.sleep"):
                    playback.start(session, FakeClient())

        bluetooth_device.assert_not_called()
        self.assertEqual(playback.audio_output_device, "")
        self.assertIsNone(playback.playbin.properties["audio-sink"])

    def test_set_volume_state_applies_gstreamer_volume(self) -> None:
        playback = GStreamerPlayback()
        playback.playbin = FakePlaybin()

        playback.set_volume_state(75, muted=False)

        self.assertEqual(playback.volume_percent, 75)
        self.assertFalse(playback.muted)
        self.assertAlmostEqual(playback.playbin.properties["volume"], 0.75)
        self.assertNotIn("mute", playback.playbin.properties)

    def test_spoken_navigation_temporarily_ducks_and_restores_playback(self) -> None:
        playback = GStreamerPlayback()
        playback.playbin = FakePlaybin()
        playback.volume_percent = 75

        with patch("abs_kids_player.playback.time.sleep"):
            playback.set_spoken_navigation_ducked(True)
            ducked_volume = playback.playbin.properties["volume"]
            playback.set_spoken_navigation_ducked(False)

        self.assertAlmostEqual(ducked_volume, 0.75 * SPOKEN_NAVIGATION_DUCK_FACTOR)
        self.assertAlmostEqual(playback.playbin.properties["volume"], 0.75)

    def test_muted_volume_sets_effective_gstreamer_volume_to_zero(self) -> None:
        playback = GStreamerPlayback()
        playback.playbin = FakePlaybin()

        playback.set_volume_state(75, muted=True)

        self.assertEqual(playback.volume_percent, 75)
        self.assertTrue(playback.muted)
        self.assertAlmostEqual(playback.playbin.properties["volume"], SILENCE_VOLUME_FLOOR)
        self.assertNotIn("mute", playback.playbin.properties)

    def test_zero_volume_counts_as_muted(self) -> None:
        playback = GStreamerPlayback()
        playback.playbin = FakePlaybin()

        playback.set_volume_state(0, muted=False)

        self.assertTrue(playback.muted)
        self.assertAlmostEqual(playback.playbin.properties["volume"], SILENCE_VOLUME_FLOOR)

    def test_missing_mute_property_does_not_block_volume_control(self) -> None:
        playback = GStreamerPlayback()
        playback.playbin = FakePlaybin(reject_mute=True)

        playback.set_volume_state(40, muted=False)

        self.assertAlmostEqual(playback.playbin.properties["volume"], 0.4)
        self.assertNotIn("mute", playback.playbin.properties)

    def test_mute_pause_can_skip_progress_sync(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.client = FakeClient()
        playback.session = SimpleNamespace(library_item_id="book-1", duration=300)
        playback.current_time = 42
        playback.is_playing = True
        playback.playbin.position = 42

        with patch("abs_kids_player.playback.time.sleep"):
            playback.pause(sync=False)

        self.assertFalse(playback.is_playing)
        self.assertTrue(playback.soft_paused)
        self.assertEqual(playback.soft_pause_time, 42)
        self.assertAlmostEqual(playback.playbin.properties["volume"], SILENCE_VOLUME_FLOOR)
        self.assertEqual(playback.playbin.states, [])
        self.assertEqual(playback.client.calls, [])

    def test_mute_resume_can_skip_progress_sync(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.client = FakeClient()
        playback.session = SimpleNamespace(library_item_id="book-1", duration=300)
        playback.current_time = 42

        with patch("abs_kids_player.playback.time.sleep"):
            playback.resume(sync=False)

        self.assertTrue(playback.is_playing)
        self.assertEqual(playback.playbin.states[-1], FakeGst.State.PLAYING)
        self.assertEqual(playback.client.calls, [])

    def test_smart_resume_rewind_depends_on_pause_duration(self) -> None:
        self.assertEqual(smart_resume_rewind_seconds(9.9), 0)
        self.assertEqual(smart_resume_rewind_seconds(10), 3)
        self.assertEqual(smart_resume_rewind_seconds(299), 3)
        self.assertEqual(smart_resume_rewind_seconds(300), 8)

    def test_soft_pause_resume_seeks_back_after_long_pause(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.client = FakeClient()
        playback.session = SimpleNamespace(
            library_item_id="book-1",
            duration=300,
            tracks=[SimpleNamespace(start_offset=0, duration=300)],
        )
        playback.current_time = 42
        playback.volume_percent = 50
        playback.playbin.position = 42

        with patch("abs_kids_player.playback.time.sleep"):
            with patch("abs_kids_player.playback.time.monotonic", side_effect=[100.0, 112.0]):
                playback.pause(sync=False)
                playback.current_time = 100
                playback.resume(sync=False)

        self.assertTrue(playback.is_playing)
        self.assertFalse(playback.soft_paused)
        self.assertEqual(playback.current_time, 39)
        self.assertEqual(playback.playbin.seeks[-1], (FakeGst.Format.TIME, 3, 39))
        self.assertAlmostEqual(playback.playbin.properties["volume"], 0.5)

    def test_soft_pause_resume_does_not_rewind_after_short_pause(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.client = FakeClient()
        playback.session = SimpleNamespace(
            library_item_id="book-1",
            duration=300,
            tracks=[SimpleNamespace(start_offset=0, duration=300)],
        )
        playback.current_time = 42

        with patch("abs_kids_player.playback.time.sleep"):
            with patch("abs_kids_player.playback.time.monotonic", side_effect=[100.0, 105.0]):
                playback.pause(sync=False)
                playback.current_time = 100
                playback.resume(sync=False)

        self.assertEqual(playback.current_time, 42)
        self.assertEqual(playback.playbin.seeks[-1], (FakeGst.Format.TIME, 3, 42))

    def test_soft_pause_resume_owns_fade_up_to_new_volume(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.client = FakeClient()
        playback.session = SimpleNamespace(
            library_item_id="book-1",
            duration=300,
            tracks=[SimpleNamespace(start_offset=0, duration=300)],
        )
        playback.current_time = 42
        playback.volume_percent = 0
        playback.muted = True
        playback.soft_paused = True
        playback.soft_pause_time = 42
        playback._effective_volume = SILENCE_VOLUME_FLOOR

        with patch("abs_kids_player.playback.time.sleep"):
            playback.resume(sync=False, percent=50, muted=False)

        self.assertEqual(playback.playbin.volume_values[0], SILENCE_VOLUME_FLOOR)
        self.assertEqual(playback.playbin.states[-1], FakeGst.State.PLAYING)
        self.assertAlmostEqual(playback.playbin.volume_values[-1], 0.5)
        self.assertFalse(playback.muted)

    def test_soft_pause_fades_volume_down(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.client = FakeClient()
        playback.session = SimpleNamespace(library_item_id="book-1", duration=300)
        playback.current_time = 42
        playback.volume_percent = 50
        playback._effective_volume = 0.5

        with patch("abs_kids_player.playback.time.sleep"):
            playback.pause(sync=False)

        self.assertGreater(len(playback.playbin.volume_values), 1)
        self.assertAlmostEqual(playback.playbin.volume_values[-1], SILENCE_VOLUME_FLOOR)
        self.assertGreater(playback.playbin.volume_values[0], playback.playbin.volume_values[-1])

    def test_poll_does_not_query_position_while_paused(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.is_playing = False

        playback.poll()

        self.assertEqual(playback.playbin.query_position_calls, 0)

    def test_poll_stops_after_end_of_session_clears_player(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playbin = FakePlaybin()
        playback.playbin = playbin
        playback.is_playing = True

        with patch.object(playback, "handle_bus_messages", side_effect=playback.stop):
            playback.poll()

        self.assertEqual(playbin.query_position_calls, 0)
        self.assertFalse(playback.is_playing)

    def test_multifile_audiobook_advances_only_within_active_session(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        session = SimpleNamespace(
            id="session-1",
            library_item_id="book-1",
            duration=200,
            tracks=[
                SimpleNamespace(start_offset=0, duration=100, url="http://example.test/part-1.mp3"),
                SimpleNamespace(start_offset=100, duration=100, url="http://example.test/part-2.mp3"),
            ],
        )
        playback.session = session
        playback.client = FakeClient()
        playback.is_playing = True

        with patch.object(playback, "load_current_track") as load_current_track:
            advanced = playback.advance_within_session()

        self.assertTrue(advanced)
        self.assertIs(playback.session, session)
        self.assertEqual(playback.session.library_item_id, "book-1")
        self.assertEqual(playback.track_index, 1)
        self.assertEqual(playback.current_time, 100)
        load_current_track.assert_called_once_with()

    def test_completed_audiobook_stops_instead_of_starting_another_book(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.session = SimpleNamespace(
            id="session-1",
            library_item_id="book-1",
            duration=100,
            tracks=[SimpleNamespace(start_offset=0, duration=100, url="http://example.test/book.mp3")],
        )
        playback.client = FakeClient()
        playback.is_playing = True

        with patch.object(playback, "request_progress_sync") as sync_progress:
            advanced = playback.advance_within_session()

        self.assertFalse(advanced)
        sync_progress.assert_called_once_with()
        self.assertIsNone(playback.session)
        self.assertIsNone(playback.playbin)
        self.assertFalse(playback.is_playing)

    def test_completed_podcast_stops_instead_of_starting_another_title(self) -> None:
        playback = GStreamerPlayback()
        playback.Gst = FakeGst()
        playback.playbin = FakePlaybin()
        playback.session = SimpleNamespace(
            id="podcast:yoto-daily",
            library_item_id="podcast:yoto-daily",
            duration=600,
            tracks=[SimpleNamespace(start_offset=0, duration=600, url="http://example.test/episode.mp3")],
        )
        playback.client = FakeClient()
        playback.is_playing = True

        with patch.object(playback, "request_progress_sync"):
            advanced = playback.advance_within_session()

        self.assertFalse(advanced)
        self.assertIsNone(playback.session)
        self.assertIsNone(playback.playbin)
        self.assertFalse(playback.is_playing)

    def test_sync_progress_passes_session_id_and_time_listened(self) -> None:
        playback = GStreamerPlayback()
        client = FakeClient()
        playback.client = client
        playback.session = SimpleNamespace(id="play-1", library_item_id="book-1", duration=300)
        playback.current_time = 42
        playback.is_playing = True

        with patch("abs_kids_player.playback.time.monotonic", return_value=112.0):
            playback.last_sync = 100.0
            playback.sync_progress()

        self.assertEqual(client.calls[0][:4], ("book-1", 42, 300, "play-1"))
        self.assertEqual(client.calls[0][4], 12.0)


if __name__ == "__main__":
    unittest.main()
