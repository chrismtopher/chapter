from __future__ import annotations

import unittest
from unittest.mock import patch

from abs_kids_player.spoken_navigation import SpokenNavigationFeedback


class FakePipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, command: list[str], **kwargs) -> None:
        self.command = command
        self.kwargs = kwargs
        self.stdout = FakePipe() if kwargs.get("stdout") == -1 else None
        self.returncode: int | None = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


class SpokenNavigationFeedbackTest(unittest.TestCase):
    def test_debounces_title_and_routes_audio_to_selected_device(self) -> None:
        now = [10.0]
        processes: list[FakeProcess] = []
        ducked: list[bool] = []

        def process_factory(command, **kwargs):
            process = FakeProcess(command, **kwargs)
            processes.append(process)
            return process

        feedback = SpokenNavigationFeedback(
            ducked.append,
            process_factory=process_factory,
            clock=lambda: now[0],
        )
        feedback.request("The Wild Robot", delay_seconds=0.45, volume_percent=50)
        self.assertFalse(feedback.ready_to_start)

        with patch("abs_kids_player.spoken_navigation.shutil.which", return_value="/usr/bin/tool"):
            feedback.poll("bluealsa:test")
            self.assertEqual(processes, [])
            now[0] += 0.5
            self.assertTrue(feedback.ready_to_start)
            feedback.poll("bluealsa:test")

        self.assertEqual(ducked, [True])
        self.assertEqual(processes[0].command[-1], "The Wild Robot")
        self.assertIn("100", processes[0].command)
        self.assertEqual(processes[1].command, ["aplay", "-q", "-D", "bluealsa:test"])
        self.assertTrue(processes[0].stdout.closed)

        processes[0].returncode = 0
        processes[1].returncode = 0
        feedback.poll()
        self.assertEqual(ducked, [True, False])

    def test_new_selection_cancels_old_speech_and_only_speaks_latest(self) -> None:
        now = [0.0]
        processes: list[FakeProcess] = []

        def process_factory(command, **kwargs):
            process = FakeProcess(command, **kwargs)
            processes.append(process)
            return process

        feedback = SpokenNavigationFeedback(process_factory=process_factory, clock=lambda: now[0])
        feedback.request("First", delay_seconds=0.45)
        now[0] = 0.2
        feedback.request("Second", delay_seconds=0.45)
        now[0] = 0.7

        with patch("abs_kids_player.spoken_navigation.shutil.which", return_value="/usr/bin/tool"):
            feedback.poll()

        self.assertEqual(processes[0].command[-1], "Second")

    def test_muted_request_does_not_start_speech(self) -> None:
        processes = []
        feedback = SpokenNavigationFeedback(process_factory=lambda *args, **kwargs: processes.append(args))

        feedback.request("Home", muted=True)
        feedback.poll()

        self.assertEqual(processes, [])
        self.assertIsNone(feedback.pending)
