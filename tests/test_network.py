from __future__ import annotations

import unittest

from abs_kids_player.network import ip_address_frame, wifi_setup_frame


class NetworkTest(unittest.TestCase):
    def test_ip_address_frame_shows_setup_url(self) -> None:
        frame = ip_address_frame("192.168.1.42")

        self.assertEqual(frame.top, "Setup address")
        self.assertEqual(frame.bottom, "http://192.168.1.42")

    def test_ip_address_frame_can_show_direct_port(self) -> None:
        frame = ip_address_frame("192.168.1.42", port=47831)

        self.assertEqual(frame.top, "Setup address")
        self.assertEqual(frame.bottom, "http://192.168.1.42:47831")

    def test_ip_address_frame_handles_missing_ip(self) -> None:
        frame = ip_address_frame("IP unavailable")

        self.assertEqual(frame.top, "Setup address")
        self.assertEqual(frame.bottom, "IP unavailable")

    def test_wifi_setup_frame_tells_user_what_to_do(self) -> None:
        frame = wifi_setup_frame("Chapter-Setup", "http://10.42.0.1")

        self.assertEqual(frame.top, "Connect to Chapter-Setup")
        self.assertEqual(frame.bottom, "Browse to http://10.42.0.1")


if __name__ == "__main__":
    unittest.main()
